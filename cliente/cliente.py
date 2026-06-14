#!/usr/bin/env python3
"""
Cliente gerador de carga — Fase 3
==================================

Responsabilidades:
  - Selecionar aleatoriamente: modelo (1=60×60 / 2=30×30),
    algoritmo (CGNE/CGNR) e se aplica o ganho de sinal γ.
  - Aplicar o ganho γ ao sinal g ANTES de enviar.
  - Enviar o MESMO sinal (com ou sem ganho) para os DOIS servidores.
  - Suportar N clientes concorrentes com intervalos aleatórios.
  - Gerar relatório JSON + HTML com imagens reconstruídas.

Uso:
  python cliente.py [opções]

Opções:
  --clientes        N de clientes concorrentes          (padrão: 2)
  --requisicoes     Total de requisições a disparar     (padrão: 6)
  --intervalo-min   Intervalo mín. entre reqs (seg)     (padrão: 0.5)
  --intervalo-max   Intervalo máx. entre reqs (seg)     (padrão: 3.0)
  --url-python      URL do servidor Python              (padrão: http://localhost:8000)
  --url-csharp      URL do servidor C#                  (padrão: http://localhost:5249)
  --sem-csharp      Pula o servidor C# (se não estiver no ar)
  --sem-ganho       Nunca aplica o ganho γ
  --seed            Semente aleatória para reprodutibilidade
"""

import argparse
import base64
import io
import json
import math
import os
import random
import sys
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

import numpy as np
import requests

# ─────────────────────────────────────────────────────────────────────────────
# Configuração dos modelos
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DADOS_DIR  = os.path.join(BASE_DIR, "..")
REL_DIR    = os.path.join(BASE_DIR, "relatorios")
os.makedirs(REL_DIR, exist_ok=True)

MODELOS = {
    1: {
        "h":      os.path.join(DADOS_DIR, "dados", "modelo1", "H-1.csv"),
        "sinais": [
            os.path.join(DADOS_DIR, "dados", "modelo1", "g-60x60-1.csv"),
            os.path.join(DADOS_DIR, "dados", "modelo1", "g-60x60-2.csv"),
        ],
        "S": 794, "N_sensores": 64, "pixels": "60x60",
    },
    2: {
        "h":      os.path.join(DADOS_DIR, "dados", "modelo2", "H-2.csv"),
        "sinais": [
            os.path.join(DADOS_DIR, "dados", "modelo2", "g-30x30-1.csv"),
            os.path.join(DADOS_DIR, "dados", "modelo2", "g-30x30-2.csv"),
        ],
        "S": 436, "N_sensores": 64, "pixels": "30x30",
    },
}

ALGORITMOS = ["CGNE", "CGNR"]

# ─────────────────────────────────────────────────────────────────────────────
# Terminal colorido
# ─────────────────────────────────────────────────────────────────────────────

class Cor:
    RESET  = "\033[0m"
    VERDE  = "\033[92m"
    AZUL   = "\033[94m"
    AMARELO= "\033[93m"
    VERMELHO="\033[91m"
    CINZA  = "\033[90m"
    NEGRITO= "\033[1m"

_print_lock = threading.Lock()

def log(msg: str, cor: str = Cor.RESET):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with _print_lock:
        print(f"{Cor.CINZA}[{ts}]{Cor.RESET} {cor}{msg}{Cor.RESET}")

# ─────────────────────────────────────────────────────────────────────────────
# Ganho de sinal γ  (enunciado — aplicado pelo cliente)
# ─────────────────────────────────────────────────────────────────────────────

def aplicar_ganho(g: np.ndarray, S: int, N: int) -> np.ndarray:
    """
    Fórmula do enunciado:
      for c = 1..N
        for l = 1..S
          γ_l = 100 + (1/20) * l * sqrt(l)
          g[l,c] = g[l,c] * γ_l

    g é organizado em row-major: índice flat = (l-1)*N + (c-1)
    → aplicamos γ_l a cada linha l (broadcast sobre os N sensores).
    """
    resultado = g.astype(np.float64).copy()
    l_idx  = np.arange(1, S + 1, dtype=np.float64)            # 1..S
    gamma  = 100.0 + (1.0 / 20.0) * l_idx * np.sqrt(l_idx)   # (S,)
    g_2d   = resultado[: S * N].reshape(S, N)
    g_2d  *= gamma[:, np.newaxis]                              # broadcast (S,1)
    resultado[: S * N] = g_2d.reshape(-1)
    return resultado

def carregar_g(caminho: str) -> np.ndarray:
    """Lê o CSV do sinal g — um valor por linha."""
    valores = []
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                try:
                    valores.append(float(linha))
                except ValueError:
                    pass
    return np.array(valores, dtype=np.float64)

def g_para_csv_bytes(g: np.ndarray, nome_original: str) -> tuple[bytes, str]:
    """Serializa g de volta para CSV (um valor por linha) e retorna (bytes, nome)."""
    linhas = "\n".join(f"{v:.10g}" for v in g)
    return linhas.encode("utf-8"), nome_original

# ─────────────────────────────────────────────────────────────────────────────
# Estrutura de resultado por requisição
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ResultadoRequisicao:
    id_req:          int
    id_cliente:      int
    modelo:          int
    pixels:          str
    algoritmo:       str
    ganho_aplicado:  bool
    arquivo_sinal:   str

    # Python
    py_ok:           bool          = False
    py_iteracoes:    int           = 0
    py_tempo_s:      float         = 0.0
    py_inicio:       str           = ""
    py_termino:      str           = ""
    py_arquivo_img:  str           = ""
    py_imagem_b64:   str           = ""
    py_erro:         str           = ""

    # C#
    cs_ok:           bool          = False
    cs_iteracoes:    int           = 0
    cs_tempo_s:      float         = 0.0
    cs_inicio:       str           = ""
    cs_termino:      str           = ""
    cs_arquivo_img:  str           = ""
    cs_erro:         str           = ""

# ─────────────────────────────────────────────────────────────────────────────
# Envio para um servidor
# ─────────────────────────────────────────────────────────────────────────────

def enviar_para_servidor(
    url_base: str,
    h_bytes: bytes,
    h_nome: str,
    g_bytes: bytes,
    g_nome: str,
    algoritmo: str,
    timeout: int = 600,
) -> tuple[bool, dict, float, str]:
    """
    Envia multipart/form-data para POST /api/v1/reconstruct.
    Retorna (sucesso, data_dict, tempo_seg, mensagem_erro).
    """
    t0 = time.perf_counter()
    try:
        resp = requests.post(
            f"{url_base}/api/v1/reconstruct",
            files={
                "ArquivoMatrizCsv": (h_nome, io.BytesIO(h_bytes), "text/csv"),
                "ArquivoSinalG":    (g_nome, io.BytesIO(g_bytes), "text/csv"),
            },
            data={"Algoritmo": algoritmo},
            timeout=timeout,
        )
        elapsed = time.perf_counter() - t0
        body = resp.json()
        if resp.status_code == 200 and not body.get("errors"):
            return True, body.get("data", {}), elapsed, ""
        erros = body.get("errors", [str(resp.status_code)])
        return False, {}, elapsed, " | ".join(erros)
    except Exception as exc:
        return False, {}, time.perf_counter() - t0, str(exc)

# ─────────────────────────────────────────────────────────────────────────────
# Worker — um "cliente" que dispara requisições
# ─────────────────────────────────────────────────────────────────────────────

def worker(
    id_cliente: int,
    ids_req: list[int],
    args,
    h_cache: dict,          # {modelo_id: bytes}  — pré-carregado
    resultados: list,
    lock: threading.Lock,
):
    for id_req in ids_req:
        # ── Seleção aleatória ────────────────────────────────────────────────
        modelo_id  = random.choice(list(MODELOS.keys()))
        algoritmo  = random.choice(ALGORITMOS)
        usar_ganho = random.choice([True, False]) if not args.sem_ganho else False
        modelo     = MODELOS[modelo_id]
        sinal_path = random.choice(modelo["sinais"])
        sinal_nome = os.path.basename(sinal_path)

        log(
            f"[C{id_cliente}|R{id_req}] modelo={modelo['pixels']} "
            f"algo={algoritmo} ganho={'SIM' if usar_ganho else 'NAO'} "
            f"sinal={sinal_nome}",
            Cor.AZUL,
        )

        # ── Carrega e processa g ─────────────────────────────────────────────
        g = carregar_g(sinal_path)
        if usar_ganho:
            g = aplicar_ganho(g, modelo["S"], modelo["N_sensores"])
            log(f"[C{id_cliente}|R{id_req}] ganho γ aplicado", Cor.AMARELO)

        g_bytes, g_nome = g_para_csv_bytes(g, sinal_nome)
        h_bytes = h_cache[modelo_id]
        h_nome  = os.path.basename(modelo["h"])

        resultado = ResultadoRequisicao(
            id_req=id_req,
            id_cliente=id_cliente,
            modelo=modelo_id,
            pixels=modelo["pixels"],
            algoritmo=algoritmo,
            ganho_aplicado=usar_ganho,
            arquivo_sinal=sinal_nome,
        )

        # ── Envia para Python ────────────────────────────────────────────────
        log(f"[C{id_cliente}|R{id_req}] → Python {args.url_python}", Cor.VERDE)
        ok, data, tempo, erro = enviar_para_servidor(
            args.url_python, h_bytes, h_nome, g_bytes, g_nome, algoritmo
        )
        resultado.py_ok          = ok
        resultado.py_tempo_s     = round(tempo, 3)
        if ok:
            resultado.py_iteracoes   = data.get("iteracoesExecutadas", 0)
            resultado.py_inicio      = data.get("inicioReconstrucao", "")
            resultado.py_termino     = data.get("terminoReconstrucao", "")
            resultado.py_arquivo_img = data.get("arquivoImagem", "")
            resultado.py_imagem_b64  = data.get("imagemBase64", "")
            log(
                f"[C{id_cliente}|R{id_req}] ✓ Python  "
                f"{tempo:.2f}s  iter={resultado.py_iteracoes}",
                Cor.VERDE,
            )
        else:
            resultado.py_erro = erro
            log(f"[C{id_cliente}|R{id_req}] ✗ Python  {erro}", Cor.VERMELHO)

        # ── Envia para C# (mesmo g) ──────────────────────────────────────────
        if not args.sem_csharp:
            log(f"[C{id_cliente}|R{id_req}] → C#     {args.url_csharp}", Cor.VERDE)
            ok_cs, data_cs, tempo_cs, erro_cs = enviar_para_servidor(
                args.url_csharp, h_bytes, h_nome, g_bytes, g_nome, algoritmo
            )
            resultado.cs_ok          = ok_cs
            resultado.cs_tempo_s     = round(tempo_cs, 3)
            if ok_cs:
                resultado.cs_iteracoes   = data_cs.get("iteracoesExecutadas", 0)
                resultado.cs_inicio      = data_cs.get("inicioReconstrucao", "")
                resultado.cs_termino     = data_cs.get("terminoReconstrucao", "")
                resultado.cs_arquivo_img = data_cs.get("arquivoImagem", "")
                log(
                    f"[C{id_cliente}|R{id_req}] ✓ C#     "
                    f"{tempo_cs:.2f}s  iter={resultado.cs_iteracoes}",
                    Cor.VERDE,
                )
            else:
                resultado.cs_erro = erro_cs
                log(f"[C{id_cliente}|R{id_req}] ✗ C#     {erro_cs}", Cor.VERMELHO)
        else:
            resultado.cs_ok  = False
            resultado.cs_erro = "servidor C# ignorado (--sem-csharp)"

        with lock:
            resultados.append(resultado)

        # ── Intervalo aleatório antes da próxima requisição ──────────────────
        if id_req != ids_req[-1]:
            espera = random.uniform(args.intervalo_min, args.intervalo_max)
            log(f"[C{id_cliente}] aguardando {espera:.2f}s...", Cor.CINZA)
            time.sleep(espera)

# ─────────────────────────────────────────────────────────────────────────────
# Gerador de relatório
# ─────────────────────────────────────────────────────────────────────────────

def gerar_relatorio(resultados: list[ResultadoRequisicao], args) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON
    json_path = os.path.join(REL_DIR, f"relatorio_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            [asdict(r) for r in resultados],
            f, indent=2, ensure_ascii=False,
        )

    # Métricas resumo
    py_ok  = [r for r in resultados if r.py_ok]
    cs_ok  = [r for r in resultados if r.cs_ok]
    py_avg = sum(r.py_tempo_s for r in py_ok) / len(py_ok) if py_ok else 0
    cs_avg = sum(r.cs_tempo_s for r in cs_ok) / len(cs_ok) if cs_ok else 0

    # HTML
    html_path = os.path.join(REL_DIR, f"relatorio_{ts}.html")

    linhas_tabela = ""
    for r in sorted(resultados, key=lambda x: x.id_req):
        img_tag = ""
        if r.py_imagem_b64:
            img_tag = (
                f'<img src="data:image/png;base64,{r.py_imagem_b64}" '
                f'style="image-rendering:pixelated;width:120px;height:120px;" '
                f'title="Python — {r.py_arquivo_img}">'
            )

        iter_match = ""
        if r.py_ok and r.cs_ok:
            if r.py_iteracoes == r.cs_iteracoes:
                iter_match = '<span style="color:#22c55e">✓</span>'
            else:
                iter_match = '<span style="color:#ef4444">✗</span>'

        py_status = (
            f'<span style="color:#22c55e">✓ {r.py_tempo_s:.2f}s / {r.py_iteracoes} iter</span>'
            if r.py_ok else f'<span style="color:#ef4444">✗ {r.py_erro[:60]}</span>'
        )
        cs_status = (
            f'<span style="color:#22c55e">✓ {r.cs_tempo_s:.2f}s / {r.cs_iteracoes} iter</span>'
            if r.cs_ok else f'<span style="color:#ef4444">✗ {r.cs_erro[:60]}</span>'
        )

        linhas_tabela += f"""
        <tr>
          <td>{r.id_req}</td>
          <td>C{r.id_cliente}</td>
          <td>{r.pixels}</td>
          <td><code>{r.algoritmo}</code></td>
          <td>{'Sim' if r.ganho_aplicado else 'Não'}</td>
          <td>{py_status}</td>
          <td>{cs_status}</td>
          <td>{iter_match}</td>
          <td>{img_tag}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>Relatório — Reconstrução de Imagens</title>
  <style>
    body  {{ font-family: system-ui, sans-serif; background:#0f172a; color:#e2e8f0; padding:2rem; }}
    h1    {{ color:#38bdf8; }}
    h2    {{ color:#94a3b8; margin-top:2rem; }}
    table {{ border-collapse:collapse; width:100%; margin-top:1rem; }}
    th    {{ background:#1e293b; padding:.6rem 1rem; text-align:left; color:#7dd3fc; }}
    td    {{ padding:.5rem 1rem; border-bottom:1px solid #1e293b; vertical-align:middle; }}
    tr:hover td {{ background:#1e293b; }}
    code  {{ background:#334155; padding:.2rem .4rem; border-radius:.25rem; color:#f0abfc; }}
    .card {{ background:#1e293b; border-radius:.75rem; padding:1.5rem; margin:.5rem; flex:1; }}
    .cards {{ display:flex; flex-wrap:wrap; gap:.5rem; margin-top:1rem; }}
    .num  {{ font-size:2rem; font-weight:700; color:#38bdf8; }}
    .lbl  {{ color:#94a3b8; font-size:.85rem; }}
  </style>
</head>
<body>
  <h1>Relatório de Reconstrução de Imagens Tomográficas</h1>
  <p>Gerado em: <strong>{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</strong>
     &nbsp;|&nbsp; Clientes: <strong>{args.clientes}</strong>
     &nbsp;|&nbsp; Requisições: <strong>{len(resultados)}</strong>
  </p>

  <h2>Resumo</h2>
  <div class="cards">
    <div class="card">
      <div class="num">{len(py_ok)}/{len(resultados)}</div>
      <div class="lbl">Sucesso Python</div>
    </div>
    <div class="card">
      <div class="num">{py_avg:.2f}s</div>
      <div class="lbl">Tempo médio Python</div>
    </div>
    <div class="card">
      <div class="num">{len(cs_ok)}/{len(resultados)}</div>
      <div class="lbl">Sucesso C#</div>
    </div>
    <div class="card">
      <div class="num">{cs_avg:.2f}s</div>
      <div class="lbl">Tempo médio C#</div>
    </div>
    <div class="card">
      <div class="num">{'Python' if py_avg < cs_avg and py_avg > 0 else 'C#' if cs_avg > 0 else 'N/A'}</div>
      <div class="lbl">Mais rápido</div>
    </div>
  </div>

  <h2>Detalhamento por Requisição</h2>
  <table>
    <thead>
      <tr>
        <th>#</th><th>Cliente</th><th>Pixels</th><th>Algoritmo</th>
        <th>Ganho γ</th><th>Python</th><th>C#</th><th>Iter. match</th><th>Imagem (Python)</th>
      </tr>
    </thead>
    <tbody>
      {linhas_tabela}
    </tbody>
  </table>
</body>
</html>"""

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    return json_path, html_path

# ─────────────────────────────────────────────────────────────────────────────
# Pré-carregamento dos arquivos H
# ─────────────────────────────────────────────────────────────────────────────

def precarregar_h(modelos_usados: list[int]) -> dict:
    """Lê os arquivos H uma vez em memória para reusar em todas as threads."""
    cache = {}
    for mid in modelos_usados:
        path = MODELOS[mid]["h"]
        log(f"Pré-carregando H (modelo {mid}): {os.path.basename(path)} ...", Cor.AMARELO)
        t0 = time.perf_counter()
        with open(path, "rb") as f:
            cache[mid] = f.read()
        log(
            f"Modelo {mid} carregado: "
            f"{len(cache[mid]) / 1e6:.1f} MB em {time.perf_counter()-t0:.1f}s",
            Cor.AMARELO,
        )
    return cache

# ─────────────────────────────────────────────────────────────────────────────
# Health-check dos servidores
# ─────────────────────────────────────────────────────────────────────────────

def health_check(url: str, nome: str) -> bool:
    """
    Verifica se o servidor está no ar.
    - Primeiro tenta GET /api/v1/health (Python tem esse endpoint).
    - Se retornar qualquer resposta HTTP (inclusive 404/405), o servidor
      está no ar (C# não tem /health mas responde na porta).
    - Só falha se houver erro de conexão (ConnectionError / Timeout).
    """
    try:
        r = requests.get(f"{url}/api/v1/health", timeout=5)
        if r.status_code == 200:
            try:
                info = r.json().get("servidor", nome)
            except Exception:
                info = nome
            log(f"✓ {nome} ({url}) — online  [{info}]", Cor.VERDE)
        else:
            # Qualquer resposta HTTP significa que o servidor está no ar
            log(f"✓ {nome} ({url}) — online  [HTTP {r.status_code}]", Cor.VERDE)
        return True
    except requests.exceptions.ConnectionError:
        log(f"✗ {nome} ({url}) — offline (connection refused)", Cor.VERMELHO)
        return False
    except requests.exceptions.Timeout:
        log(f"✗ {nome} ({url}) — offline (timeout)", Cor.VERMELHO)
        return False
    except Exception as exc:
        log(f"✗ {nome} ({url}) — offline ({exc})", Cor.VERMELHO)
        return False

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Cliente gerador de carga — Reconstrução de Imagens",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
          Exemplos:
            python cliente.py --clientes 3 --requisicoes 9
            python cliente.py --clientes 5 --requisicoes 20 --sem-csharp
            python cliente.py --sem-csharp --sem-ganho --seed 42
        """),
    )
    parser.add_argument("--clientes",      type=int,   default=2,                          help="N de clientes concorrentes")
    parser.add_argument("--requisicoes",   type=int,   default=6,                          help="Total de requisições")
    parser.add_argument("--intervalo-min", type=float, default=0.5,  dest="intervalo_min", help="Intervalo mínimo entre reqs (s)")
    parser.add_argument("--intervalo-max", type=float, default=3.0,  dest="intervalo_max", help="Intervalo máximo entre reqs (s)")
    parser.add_argument("--url-python",    type=str,   default="http://localhost:8000",    help="URL do servidor Python")
    parser.add_argument("--url-csharp",    type=str,   default="http://localhost:5249",    help="URL do servidor C#")
    parser.add_argument("--sem-csharp",    action="store_true",                            help="Pula o servidor C#")
    parser.add_argument("--sem-ganho",     action="store_true",                            help="Nunca aplica o ganho γ")
    parser.add_argument("--seed",          type=int,   default=None,                       help="Semente aleatória")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        np.random.seed(args.seed)

    print(f"\n{Cor.NEGRITO}{'='*60}{Cor.RESET}")
    print(f"{Cor.NEGRITO}  CLIENTE — Reconstrução de Imagens Tomográficas{Cor.RESET}")
    print(f"{Cor.NEGRITO}{'='*60}{Cor.RESET}\n")
    log(f"Clientes concorrentes : {args.clientes}", Cor.NEGRITO)
    log(f"Total de requisições  : {args.requisicoes}", Cor.NEGRITO)
    log(f"Intervalo aleatório   : [{args.intervalo_min}s, {args.intervalo_max}s]", Cor.NEGRITO)
    log(f"Servidor Python       : {args.url_python}", Cor.NEGRITO)
    log(f"Servidor C#           : {'(ignorado)' if args.sem_csharp else args.url_csharp}", Cor.NEGRITO)
    print()

    # ── Health checks ────────────────────────────────────────────────────────
    log("Verificando servidores...", Cor.AMARELO)
    py_online = health_check(args.url_python, "Python")
    cs_online = (not args.sem_csharp) and health_check(args.url_csharp, "C#")
    if args.sem_csharp:
        log("C# ignorado por --sem-csharp", Cor.CINZA)

    if not py_online:
        log("Servidor Python offline. Suba com: uvicorn main:app --port 8000", Cor.VERMELHO)
        sys.exit(1)

    if not args.sem_csharp and not cs_online:
        log("Servidor C# offline. Continuando só com Python (use --sem-csharp para suprimir este aviso).", Cor.AMARELO)
        args.sem_csharp = True

    print()

    # ── Pré-carregar H (todos os modelos possíveis) ──────────────────────────
    h_cache = precarregar_h(list(MODELOS.keys()))
    print()

    # ── Distribuir requisições entre os clientes ─────────────────────────────
    ids_por_cliente: list[list[int]] = [[] for _ in range(args.clientes)]
    for i in range(args.requisicoes):
        ids_por_cliente[i % args.clientes].append(i + 1)

    resultados: list[ResultadoRequisicao] = []
    lock = threading.Lock()
    t_inicio_total = time.perf_counter()

    log(f"Disparando {args.requisicoes} requisições com {args.clientes} cliente(s)...\n", Cor.NEGRITO)

    with ThreadPoolExecutor(max_workers=args.clientes) as executor:
        futures = [
            executor.submit(
                worker, cid + 1, ids_por_cliente[cid], args, h_cache, resultados, lock
            )
            for cid in range(args.clientes)
        ]
        for fut in as_completed(futures):
            exc = fut.exception()
            if exc:
                log(f"Erro em cliente: {exc}", Cor.VERMELHO)

    t_total = time.perf_counter() - t_inicio_total

    # ── Resumo no terminal ───────────────────────────────────────────────────
    print()
    print(f"{Cor.NEGRITO}{'='*60}{Cor.RESET}")
    log(f"Tempo total      : {t_total:.2f}s", Cor.NEGRITO)
    py_ok = [r for r in resultados if r.py_ok]
    cs_ok = [r for r in resultados if r.cs_ok]
    log(f"Python — sucesso : {len(py_ok)}/{len(resultados)}  "
        f"| tempo médio: {sum(r.py_tempo_s for r in py_ok)/len(py_ok):.2f}s"
        if py_ok else f"Python — sucesso : 0/{len(resultados)}", Cor.VERDE)
    if not args.sem_csharp:
        log(f"C#     — sucesso : {len(cs_ok)}/{len(resultados)}  "
            f"| tempo médio: {sum(r.cs_tempo_s for r in cs_ok)/len(cs_ok):.2f}s"
            if cs_ok else f"C#     — sucesso : 0/{len(resultados)}", Cor.VERDE)

    # Validação de paridade iterações Python == C#
    pares = [(r.py_iteracoes, r.cs_iteracoes) for r in resultados if r.py_ok and r.cs_ok]
    if pares:
        iguais = sum(1 for a, b in pares if a == b)
        log(f"Iterações Python==C# : {iguais}/{len(pares)} requisições", Cor.VERDE if iguais == len(pares) else Cor.AMARELO)

    # ── Gerar relatório ──────────────────────────────────────────────────────
    print()
    log("Gerando relatório...", Cor.AMARELO)
    json_path, html_path = gerar_relatorio(resultados, args)
    log(f"JSON : {json_path}", Cor.AZUL)
    log(f"HTML : {html_path}", Cor.AZUL)
    print(f"\n{Cor.NEGRITO}{'='*60}{Cor.RESET}\n")


if __name__ == "__main__":
    import argparse
    main()
