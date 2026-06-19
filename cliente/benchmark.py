#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Benchmark comparativo — Fase 4
================================
Roda o mesmo conjunto de requisições com 1, 2, 4 e 8 clientes concorrentes
e mede throughput, tempos (avg / p50 / p95) e uso de CPU/RAM dos servidores.

Uso:
  python benchmark.py
  python benchmark.py --url-python http://localhost:8000 --url-csharp http://localhost:5249
  python benchmark.py --sem-csharp          # só Python
  python benchmark.py --rodadas 4           # mais rodadas por cenário

Saída:
  benchmark/resultados/benchmark_YYYYMMDD_HHMMSS.html   ← relatório HTML com gráficos
  benchmark/resultados/benchmark_YYYYMMDD_HHMMSS.json   ← dados brutos
"""

import sys

# Força UTF-8 no terminal — necessário no Windows (cp1252 não suporta ✓ ✗ etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import argparse
import base64
import io
import json
import math
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import psutil
import requests

# ─────────────────────────────────────────────────────────────────────────────
# Caminhos e configuração
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
RAIZ        = os.path.join(BASE_DIR, "..")
RESULTADO_DIR = os.path.join(BASE_DIR, "benchmark_resultados")
os.makedirs(RESULTADO_DIR, exist_ok=True)

# Diretórios de cache dos servidores (apagados antes de cada cenário)
CACHE_PYTHON_IMGS = os.path.join(RAIZ, "servidor-python", "imagens")
CACHE_PYTHON_MTX  = os.path.join(RAIZ, "servidor-python", "cache")

DADOS_MODELOS = {
    1: {
        "h": os.path.join(RAIZ, "dados", "modelo1", "H-1.csv"),
        "sinais": {
            "1": os.path.join(RAIZ, "dados", "modelo1", "g-60x60-1.csv"),
            "2": os.path.join(RAIZ, "dados", "modelo1", "g-60x60-2.csv"),
        },
    },
    2: {
        "h": os.path.join(RAIZ, "dados", "modelo2", "H-2.csv"),
        "sinais": {
            "1": os.path.join(RAIZ, "dados", "modelo2", "g-30x30-1.csv"),
            "2": os.path.join(RAIZ, "dados", "modelo2", "g-30x30-2.csv"),
        },
    },
}


def construir_pacotes(modelo: int, sinal: str, algoritmo: str) -> list[dict]:
    m = DADOS_MODELOS[modelo]
    sinais = list(m["sinais"].values()) if sinal == "ambos" else [m["sinais"][sinal]]
    algoritmos = ["CGNR", "CGNE"] if algoritmo.upper() == "AMBOS" else [algoritmo.upper()]
    return [{"modelo": modelo, "h": m["h"], "g": g, "algoritmo": alg}
            for g in sinais for alg in algoritmos]


def construir_lista_clientes(n_clientes: int) -> list[int]:
    """Teste de saturação direto — roda apenas com o número de clientes escolhido."""
    return [n_clientes]


# ─────────────────────────────────────────────────────────────────────────────
# Utilitários
# ─────────────────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def limpar_cache_imagens():
    """Remove imagens geradas pelos servidores para forçar reconstrução real."""
    for caminho in [CACHE_PYTHON_IMGS]:
        if os.path.isdir(caminho):
            for f in os.listdir(caminho):
                if f.endswith(".png"):
                    os.remove(os.path.join(caminho, f))
    log("Cache de imagens limpo.")


def pids_na_porta(porta: int) -> list[int]:
    """Retorna PIDs dos processos ouvindo na porta especificada.
    Tenta via net_connections primeiro; cai para busca por nome se vazio (macOS sem root).
    """
    pids = []
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr.port == porta and conn.status == "LISTEN" and conn.pid:
                pids.append(conn.pid)
    except Exception:
        pass

    if not pids:
        # Fallback: encontra pelo nome do processo (funciona sem root no macOS)
        nomes_por_porta = {
            8000: ["uvicorn", "python", "python3"],
            5001: ["dotnet"],
        }
        nomes = nomes_por_porta.get(porta, [])
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                nome = (proc.info.get("name") or "").lower()
                cmd  = " ".join(proc.info.get("cmdline") or []).lower()
                if any(n in nome or n in cmd for n in nomes):
                    pids.append(proc.info["pid"])
            except Exception:
                pass

    return list(set(pids))


def coletar_info_sistema() -> dict:
    """Coleta informações do hardware local — funciona em macOS, Windows e Linux."""
    import platform
    so = f"{platform.system()} {platform.release()} ({platform.machine()})"

    cpu_nome = platform.processor() or "N/A"
    if platform.system() == "Darwin":
        try:
            import subprocess
            cpu_nome = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
            ).strip()
        except Exception:
            pass
    elif platform.system() == "Windows":
        try:
            import subprocess
            out = subprocess.check_output(
                ["wmic", "cpu", "get", "Name"], text=True
            ).strip().splitlines()
            cpu_nome = out[-1].strip() if len(out) > 1 else cpu_nome
        except Exception:
            pass

    freq = psutil.cpu_freq()
    mem  = psutil.virtual_memory()
    freq_ghz = round(freq.max / 1000, 2) if (freq and freq.max and freq.max > 0) else "N/A"
    return {
        "so":                  so,
        "cpu_nome":            cpu_nome,
        "cpu_nucleos_fisicos": psutil.cpu_count(logical=False) or "N/A",
        "cpu_nucleos_logicos": psutil.cpu_count(logical=True)  or "N/A",
        "cpu_freq_max_ghz":    freq_ghz,
        "ram_total_gb":        round(mem.total / 1e9, 1),
    }


def enviar_requisicao(url_base: str, pacote: dict, h_cache: dict, timeout=120) -> dict:
    """Envia uma requisição e retorna dict com tempo (s) e iterações (-1/None em erro)."""
    h_bytes = h_cache[pacote["h"]]
    g_nome  = os.path.basename(pacote["g"])
    h_nome  = os.path.basename(pacote["h"])

    with open(pacote["g"], "rb") as gf:
        g_bytes = gf.read()

    t0 = time.perf_counter()
    try:
        resp = requests.post(
            f"{url_base}/api/v1/reconstruct",
            files={
                "ArquivoMatrizCsv": (h_nome, io.BytesIO(h_bytes), "text/csv"),
                "ArquivoSinalG":    (g_nome, io.BytesIO(g_bytes), "text/csv"),
            },
            data={"Algoritmo": pacote["algoritmo"]},
            timeout=timeout,
        )
        elapsed = time.perf_counter() - t0
        if resp.status_code == 200:
            body = resp.json()
            if not body.get("errors"):
                iteracoes = (body.get("data") or {}).get("iteracoesExecutadas", None)
                return {"tempo": elapsed, "iteracoes": iteracoes}
        return {"tempo": -1, "iteracoes": None}
    except Exception:
        return {"tempo": -1, "iteracoes": None}


# ─────────────────────────────────────────────────────────────────────────────
# Monitor de CPU/RAM (thread separada)
# ─────────────────────────────────────────────────────────────────────────────

class MonitorRecursos:
    def __init__(self, pids: list[int]):
        self.pids      = pids
        self.amostras_cpu = []
        self.amostras_ram = []
        self._parar    = threading.Event()
        self._thread   = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        procs = []
        for pid in self.pids:
            try:
                procs.append(psutil.Process(pid))
            except Exception:
                pass
        while not self._parar.is_set():
            cpu, ram = 0.0, 0.0
            for p in procs:
                try:
                    cpu += p.cpu_percent(interval=None)
                    ram += p.memory_info().rss / 1e6  # MB
                except Exception:
                    pass
            if cpu > 0 or ram > 0:
                self.amostras_cpu.append(cpu)
                self.amostras_ram.append(ram)
            time.sleep(0.5)

    def iniciar(self):
        self._thread.start()

    def parar(self) -> tuple[float, float]:
        self._parar.set()
        self._thread.join()
        cpu_avg = float(np.mean(self.amostras_cpu)) if self.amostras_cpu else 0.0
        ram_avg = float(np.mean(self.amostras_ram)) if self.amostras_ram else 0.0
        return cpu_avg, ram_avg


# ─────────────────────────────────────────────────────────────────────────────
# Cenário de benchmark
# ─────────────────────────────────────────────────────────────────────────────

def rodar_cenario(url: str, n_clientes: int, rodadas: int, h_cache: dict,
                  pacotes: list[dict]) -> dict:
    """
    Roda `n_clientes` workers concorrentes, cada um enviando `rodadas`
    requisições, ciclando pelos pacotes disponíveis.
    Retorna métricas consolidadas.
    """
    total_reqs = n_clientes * rodadas
    pacotes_ciclados = [pacotes[i % len(pacotes)] for i in range(total_reqs)]
    resultados = []
    lock       = threading.Lock()

    def worker_fn(pacotes_worker):
        for p in pacotes_worker:
            r = enviar_requisicao(url, p, h_cache)
            with lock:
                resultados.append(r)

    fatias = [pacotes_ciclados[i::n_clientes] for i in range(n_clientes)]

    t_inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n_clientes) as ex:
        futs = [ex.submit(worker_fn, fatias[i]) for i in range(n_clientes)]
        for f in as_completed(futs):
            pass
    t_total = time.perf_counter() - t_inicio

    ok       = [r for r in resultados if r["tempo"] > 0]
    tempos_ok = [r["tempo"] for r in ok]
    iters_ok  = [r["iteracoes"] for r in ok if r["iteracoes"] is not None]

    if not tempos_ok:
        return {"n_clientes": n_clientes, "sucesso": 0, "total": total_reqs}

    return {
        "n_clientes"   : n_clientes,
        "total_reqs"   : total_reqs,
        "sucesso"      : len(tempos_ok),
        "throughput"   : len(tempos_ok) / t_total,
        "avg_s"        : float(np.mean(tempos_ok)),
        "p50_s"        : float(np.percentile(tempos_ok, 50)),
        "avg_iteracoes": round(float(np.mean(iters_ok)), 1) if iters_ok else None,
        "p95_s"        : float(np.percentile(tempos_ok, 95)),
        "max_s"        : float(np.max(tempos_ok)),
        "t_total_s"    : t_total,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Geração de gráficos
# ─────────────────────────────────────────────────────────────────────────────

CORES = {"Python": "#38bdf8", "C#": "#f472b6"}

def fig_para_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                facecolor="#0f172a", edgecolor="none")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def gerar_graficos(dados_py: list[dict], dados_cs: list[dict], sem_csharp: bool) -> dict[str, str]:
    """Gera gráficos matplotlib e retorna dict {nome: base64}."""
    plt.rcParams.update({
        "figure.facecolor": "#0f172a", "axes.facecolor": "#1e293b",
        "text.color": "#e2e8f0", "axes.labelcolor": "#94a3b8",
        "xtick.color": "#94a3b8", "ytick.color": "#94a3b8",
        "axes.edgecolor": "#334155", "grid.color": "#334155",
        "axes.titlecolor": "#e2e8f0",
    })

    ns_py = [d["n_clientes"] for d in dados_py if "throughput" in d]
    ns_cs = [d["n_clientes"] for d in dados_cs if "throughput" in d] if not sem_csharp else []
    graficos = {}

    # 1. Throughput
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(ns_py, [d["throughput"] for d in dados_py if "throughput" in d],
            "o-", color=CORES["Python"], lw=2, label="Python")
    if ns_cs:
        ax.plot(ns_cs, [d["throughput"] for d in dados_cs if "throughput" in d],
                "s--", color=CORES["C#"], lw=2, label="C#")
    ax.set(title="Throughput (imagens/segundo)", xlabel="Nº de clientes concorrentes",
           ylabel="img/s"); ax.legend(); ax.grid(True, alpha=0.3)
    graficos["throughput"] = fig_para_b64(fig); plt.close(fig)

    # 2. Tempo médio
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(ns_py, [d["avg_s"] for d in dados_py if "avg_s" in d],
            "o-", color=CORES["Python"], lw=2, label="Python avg")
    ax.plot(ns_py, [d["p95_s"] for d in dados_py if "p95_s" in d],
            "o:", color=CORES["Python"], lw=1.5, alpha=0.6, label="Python p95")
    if ns_cs:
        ax.plot(ns_cs, [d["avg_s"] for d in dados_cs if "avg_s" in d],
                "s-", color=CORES["C#"], lw=2, label="C# avg")
        ax.plot(ns_cs, [d["p95_s"] for d in dados_cs if "p95_s" in d],
                "s:", color=CORES["C#"], lw=1.5, alpha=0.6, label="C# p95")
    ax.set(title="Tempo de resposta (s)", xlabel="Nº de clientes", ylabel="segundos")
    ax.legend(); ax.grid(True, alpha=0.3)
    graficos["tempo"] = fig_para_b64(fig); plt.close(fig)

    # 3. Speedup Python vs C#
    if ns_cs and len(ns_py) == len(ns_cs):
        fig, ax = plt.subplots(figsize=(7, 4))
        speedups = [cs["avg_s"] / py["avg_s"]
                    for py, cs in zip(dados_py, dados_cs)
                    if "avg_s" in py and "avg_s" in cs]
        ns = [d["n_clientes"] for d in dados_py if "avg_s" in d][:len(speedups)]
        bars = ax.bar(ns, speedups, color=CORES["Python"], width=0.5)
        ax.axhline(1.0, color="#ef4444", lw=1.5, ls="--", label="Paridade (1×)")
        for bar, val in zip(bars, speedups):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                    f"{val:.2f}×", ha="center", va="bottom", fontsize=9, color="#e2e8f0")
        ax.set(title="Speedup Python vs C#  (avg_C# / avg_Python)", xlabel="Nº de clientes",
               ylabel="Speedup"); ax.legend(); ax.grid(True, alpha=0.3, axis="y")
        graficos["speedup"] = fig_para_b64(fig); plt.close(fig)

    return graficos


# ─────────────────────────────────────────────────────────────────────────────
# Relatório HTML
# ─────────────────────────────────────────────────────────────────────────────

def gerar_html(dados_py, dados_cs, graficos, sem_csharp, ts,
               config: dict | None = None) -> str:
    if config is None:
        config = {}

    sys_info = config.get("sistema", {})
    bloco_sistema = f"""
<div class="sysinfo">
  <strong>Hardware do teste</strong><br>
  🖥 <b>Sistema:</b> {sys_info.get('so','N/A')} &nbsp;|&nbsp;
  🧠 <b>CPU:</b> {sys_info.get('cpu_nome','N/A')} &nbsp;|&nbsp;
  ⚙️ <b>Núcleos:</b> {sys_info.get('cpu_nucleos_fisicos','?')} físicos / {sys_info.get('cpu_nucleos_logicos','?')} lógicos &nbsp;|&nbsp;
  ⚡ <b>Freq. máx.:</b> {sys_info.get('cpu_freq_max_ghz','N/A')} GHz &nbsp;|&nbsp;
  💾 <b>RAM total:</b> {sys_info.get('ram_total_gb','N/A')} GB
</div>""" if sys_info else ""

    def linha(d, servidor):
        if "throughput" not in d:
            return f"<tr><td>{d['n_clientes']}</td><td colspan='7' style='color:#ef4444'>Falhou</td></tr>"
        iters = f"{d['avg_iteracoes']:.1f}" if d.get('avg_iteracoes') is not None else "—"
        return (f"<tr><td>{d['n_clientes']}</td>"
                f"<td>{d['throughput']:.3f}</td>"
                f"<td>{d['avg_s']:.3f}</td>"
                f"<td>{d['p50_s']:.3f}</td>"
                f"<td>{d['p95_s']:.3f}</td>"
                f"<td>{d['cpu_pct']:.1f}%</td>"
                f"<td>{d['ram_mb']:.0f} MB</td>"
                f"<td>{iters}</td>"
                f"<td>{d['sucesso']}/{d['total_reqs']}</td></tr>")

    cabecalho_th = """<tr>
      <th title="Número de clientes enviando requisições ao mesmo tempo">Clientes<br><small style="font-weight:normal;color:#94a3b8">simultâneos</small></th>
      <th title="Imagens reconstruídas por segundo (quanto maior, melhor)">Throughput<br><small style="font-weight:normal;color:#94a3b8">imagens/segundo ↑</small></th>
      <th title="Tempo médio de resposta por requisição">Tempo Médio<br><small style="font-weight:normal;color:#94a3b8">seg/req (avg) ↓</small></th>
      <th title="Mediana — representa o caso típico">Mediana<br><small style="font-weight:normal;color:#94a3b8">seg/req (P50) ↓</small></th>
      <th title="95% das requisições foram mais rápidas que este valor">Pior Caso Freq.<br><small style="font-weight:normal;color:#94a3b8">seg/req (P95) ↓</small></th>
      <th title="Uso médio de CPU do processo servidor durante o teste">CPU Servidor<br><small style="font-weight:normal;color:#94a3b8">% médio</small></th>
      <th title="Uso médio de RAM do processo servidor durante o teste">RAM Servidor<br><small style="font-weight:normal;color:#94a3b8">MB médio</small></th>
      <th title="Média de iterações do algoritmo por reconstrução">Iterações<br><small style="font-weight:normal;color:#94a3b8">média por req</small></th>
      <th title="Requisições que retornaram com sucesso vs total enviado">Sucesso<br><small style="font-weight:normal;color:#94a3b8">ok / total</small></th>
    </tr>"""

    tabela_py = "\n".join(linha(d, "Python") for d in dados_py)
    tabela_cs = "\n".join(linha(d, "C#")     for d in dados_cs) if not sem_csharp else ""

    cs_section = "" if sem_csharp else f"""
    <h2>C# (.NET)</h2>
    <table><thead>{cabecalho_th}</thead>
    <tbody>{tabela_cs}</tbody></table>"""

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<title>Benchmark — Reconstrução de Imagens</title>
<style>
  body  {{ font-family:system-ui,sans-serif; background:#0f172a; color:#e2e8f0; padding:2rem; }}
  h1    {{ color:#38bdf8; }} h2 {{ color:#94a3b8; margin-top:2rem; }}
  table {{ border-collapse:collapse; width:100%; margin-top:1rem; }}
  th    {{ background:#1e293b; padding:.6rem 1rem; text-align:left; color:#7dd3fc; line-height:1.4; }}
  th small {{ font-size:.75em; display:block; }}
  td    {{ padding:.5rem 1rem; border-bottom:1px solid #1e293b; }}
  tr:hover td {{ background:#1e293b; }}
  .duracao  {{ background:#0f3460; border-left:4px solid #38bdf8; border-radius:.4rem; padding:.6rem 1.2rem; margin:.8rem 0 1.5rem; font-size:.95em; }}
  .legenda  {{ background:#1e293b; border-radius:.5rem; padding:1rem 1.5rem; margin:1.5rem 0; font-size:.9em; color:#94a3b8; }}
  .legenda strong {{ color:#e2e8f0; }}
</style></head><body>
<h1>Benchmark Comparativo — Reconstrução Tomográfica</h1>
<p>
  Modelo {config.get('modelo','?')} ({config.get('pixels','?')})
  &nbsp;|&nbsp; Sinal: {config.get('sinal','?')}
  &nbsp;|&nbsp; Algoritmo: {config.get('algoritmo','?')}
  &nbsp;|&nbsp; Rodadas/cliente: {config.get('rodadas_por_cliente','?')}
</p>
<div class="duracao">
  ⏱ Início: <strong>{config.get('inicio','—')}</strong>
  &nbsp;&nbsp;→&nbsp;&nbsp;
  Fim: <strong>{config.get('fim','—')}</strong>
  &nbsp;&nbsp;|&nbsp;&nbsp;
  Duração total: <strong>{config.get('duracao_fmt','—')}</strong>
</div>

<h2>Python (FastAPI + Uvicorn)</h2>
<table><thead>{cabecalho_th}</thead>
<tbody>{tabela_py}</tbody></table>
{cs_section}

<div class="legenda">
  <strong>Como ler os resultados:</strong><br>
  &bull; <strong>Throughput (img/s):</strong> quantas imagens o servidor reconstrói por segundo — <em>quanto maior, melhor</em>.<br>
  &bull; <strong>Tempo Médio (avg):</strong> média aritmética do tempo de resposta de todas as requisições — <em>quanto menor, melhor</em>.<br>
  &bull; <strong>Mediana (P50):</strong> metade das requisições respondeu abaixo deste valor; representa o caso típico do usuário.<br>
  &bull; <strong>Pior Caso Frequente (P95):</strong> 95% das requisições respondeu abaixo deste valor; os 5% mais lentos ficaram acima — indica estabilidade sob carga.<br>
  &bull; <strong>Sucesso:</strong> requisições que retornaram com sucesso vs total enviado.
</div>
</body></html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Benchmark comparativo Python vs C#")
    parser.add_argument("--url-python",    default="http://localhost:8000")
    parser.add_argument("--url-csharp",    default="http://localhost:5001")
    parser.add_argument("--sem-csharp",    action="store_true")
    parser.add_argument("--rodadas",       type=int, default=2,
                        help="Requisições por cliente por cenário (default: 2)")
    parser.add_argument("--modelo",        type=int, default=2, choices=[1, 2],
                        help="Modelo de dados: 1=60×60px  2=30×30px (default: 2)")
    parser.add_argument("--sinal",         type=str, default="ambos",
                        choices=["1", "2", "ambos"],
                        help="Sinal g a usar: 1, 2 ou ambos (default: ambos)")
    parser.add_argument("--algoritmo",     type=str, default="AMBOS",
                        choices=["CGNE", "CGNR", "AMBOS"],
                        help="Algoritmo: CGNE, CGNR ou AMBOS (default: AMBOS)")
    parser.add_argument("--max-clientes",  type=int, default=8,
                        help="Máximo de clientes concorrentes (default: 8)")
    args = parser.parse_args()

    # Constrói PACOTES e lista de clientes com base nos args
    PACOTES = construir_pacotes(args.modelo, args.sinal, args.algoritmo)
    N_CLIENTES_LISTA = construir_lista_clientes(args.max_clientes)

    pixels = "60×60" if args.modelo == 1 else "30×30"
    info_sys = coletar_info_sistema()

    log("=" * 56)
    log("  BENCHMARK — Reconstrução de Imagens Tomográficas")
    log("=" * 56)
    log(f"  Sistema  : {info_sys['so']}")
    log(f"  CPU      : {info_sys['cpu_nome']}")
    log(f"  Núcleos  : {info_sys['cpu_nucleos_fisicos']} físicos / {info_sys['cpu_nucleos_logicos']} lógicos")
    log(f"  Freq max : {info_sys['cpu_freq_max_ghz']} GHz")
    log(f"  RAM total: {info_sys['ram_total_gb']} GB")
    log(f"  Modelo    : {args.modelo} ({pixels} px)")
    log(f"  Sinal     : {args.sinal}")
    log(f"  Algoritmo : {args.algoritmo}")
    log(f"  Clientes  : {args.max_clientes} simultâneos")
    log(f"  Req/client: {args.rodadas}")
    log(f"  TOTAL     : {args.max_clientes * args.rodadas} requests por servidor")
    log("=" * 56)

    # ── Verifica servidores ──────────────────────────────────────────────────
    for url, nome in [(args.url_python, "Python"),
                      (args.url_csharp, "C#") if not args.sem_csharp else (None, None)]:
        if url is None:
            continue
        try:
            requests.get(f"{url}/api/v1/health", timeout=5)
            log(f"✓ {nome} ({url}) online")
        except Exception:
            try:
                requests.get(url, timeout=5)
                log(f"✓ {nome} ({url}) online")
            except Exception:
                log(f"✗ {nome} ({url}) offline — abortando")
                if nome == "Python":
                    sys.exit(1)
                args.sem_csharp = True

    # ── Pré-carrega H em memória ─────────────────────────────────────────────
    h_cache = {}
    for p in PACOTES:
        if p["h"] not in h_cache:
            log(f"Carregando {os.path.basename(p['h'])}...")
            with open(p["h"], "rb") as f:
                h_cache[p["h"]] = f.read()
    log("H carregadas em memória.\n")

    dados_py: list[dict] = []
    dados_cs: list[dict] = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dt_inicio_total = datetime.now()
    t_inicio_total  = time.perf_counter()

    for n in N_CLIENTES_LISTA:
        log(f"─── {n} cliente(s) concorrente(s) ───────────────────")

        # Limpa cache de imagens para medir reconstrução real
        limpar_cache_imagens()

        # Python
        log(f"  Python: rodando {n * args.rodadas} requisições ({n}×{args.rodadas})...")
        pids_py  = pids_na_porta(8000)
        mon_py   = MonitorRecursos(pids_py); mon_py.iniciar()
        metr_py  = rodar_cenario(args.url_python, n, args.rodadas, h_cache, PACOTES)
        cpu_py, ram_py = mon_py.parar()
        metr_py["cpu_pct"] = round(cpu_py, 1)
        metr_py["ram_mb"]  = round(ram_py, 1)
        dados_py.append(metr_py)
        if "throughput" in metr_py:
            log(f"  Python ✓  throughput={metr_py['throughput']:.3f} img/s  "
                f"avg={metr_py['avg_s']:.3f}s  p95={metr_py['p95_s']:.3f}s  "
                f"CPU={cpu_py:.1f}%  RAM={ram_py:.0f}MB")

        # C#
        if not args.sem_csharp:
            limpar_cache_imagens()
            log(f"  C#:     rodando {n * args.rodadas} requisições ({n}×{args.rodadas})...")
            pids_cs  = pids_na_porta(5001)
            mon_cs   = MonitorRecursos(pids_cs); mon_cs.iniciar()
            metr_cs  = rodar_cenario(args.url_csharp, n, args.rodadas, h_cache, PACOTES)
            cpu_cs, ram_cs = mon_cs.parar()
            metr_cs["cpu_pct"] = round(cpu_cs, 1)
            metr_cs["ram_mb"]  = round(ram_cs, 1)
            dados_cs.append(metr_cs)
            if "throughput" in metr_cs:
                log(f"  C#     ✓  throughput={metr_cs['throughput']:.3f} img/s  "
                    f"avg={metr_cs['avg_s']:.3f}s  p95={metr_cs['p95_s']:.3f}s  "
                    f"CPU={cpu_cs:.1f}%  RAM={ram_cs:.0f}MB")
        print()

    # ── Relatório ────────────────────────────────────────────────────────────
    duracao_total_s = time.perf_counter() - t_inicio_total
    dt_fim_total    = datetime.now()

    mins, segs = divmod(int(duracao_total_s), 60)
    duracao_fmt = f"{mins}min {segs}s" if mins else f"{segs}s"

    log(f"\nInício : {dt_inicio_total.strftime('%H:%M:%S')}")
    log(f"Fim    : {dt_fim_total.strftime('%H:%M:%S')}")
    log(f"Duração total: {duracao_fmt}")
    log("Gerando relatório...")
    graficos = {}

    json_path = os.path.join(RESULTADO_DIR, f"benchmark_{ts}.json")
    html_path = os.path.join(RESULTADO_DIR, f"benchmark_{ts}.html")

    pixels = "60×60" if args.modelo == 1 else "30×30"
    config_usada = {
        "modelo": args.modelo,
        "pixels": pixels,
        "sinal": args.sinal,
        "algoritmo": args.algoritmo,
        "rodadas_por_cliente": args.rodadas,
        "max_clientes": args.max_clientes,
        "inicio": dt_inicio_total.strftime("%d/%m/%Y %H:%M:%S"),
        "fim": dt_fim_total.strftime("%d/%m/%Y %H:%M:%S"),
        "duracao_s": round(duracao_total_s, 1),
        "duracao_fmt": duracao_fmt,
        "sistema": info_sys,
    }

    with open(json_path, "w") as f:
        json.dump({"config": config_usada, "python": dados_py, "csharp": dados_cs},
                  f, indent=2)

    with open(html_path, "w") as f:
        f.write(gerar_html(dados_py, dados_cs, graficos, args.sem_csharp, ts,
                           config_usada))

    log(f"\nJSON : {json_path}")
    log(f"HTML : {html_path}")

    import subprocess
    subprocess.Popen(["open", html_path])

    log("\nBenchmark concluído!")


if __name__ == "__main__":
    main()
