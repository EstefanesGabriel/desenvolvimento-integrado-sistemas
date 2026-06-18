"""
Dashboard — Reconstrução de Imagens Tomográficas
=================================================
Frontend Streamlit para apresentação do trabalho APS.

Execução:
  cd frontend
  streamlit run app.py
"""

import base64
import io
import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import streamlit as st
from PIL import Image

# ─────────────────────────────────────────────────────────────────────────────
# Configuração e caminhos
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ     = os.path.join(BASE_DIR, "..")

MODELOS = {
    1: {
        "label": "Modelo 1 — 60×60 pixels",
        "pixels": "60x60", "S": 794, "N": 64,
        "h": os.path.join(RAIZ, "dados", "modelo1", "H-1.csv"),
        "sinais": {
            "g-60x60-1.csv": os.path.join(RAIZ, "dados", "modelo1", "g-60x60-1.csv"),
            "g-60x60-2.csv": os.path.join(RAIZ, "dados", "modelo1", "g-60x60-2.csv"),
        },
    },
    2: {
        "label": "Modelo 2 — 30×30 pixels",
        "pixels": "30x30", "S": 436, "N": 64,
        "h": os.path.join(RAIZ, "dados", "modelo2", "H-2.csv"),
        "sinais": {
            "g-30x30-1.csv": os.path.join(RAIZ, "dados", "modelo2", "g-30x30-1.csv"),
            "g-30x30-2.csv": os.path.join(RAIZ, "dados", "modelo2", "g-30x30-2.csv"),
        },
    },
}

BENCHMARK_RESULTADOS = os.path.join(RAIZ, "cliente", "benchmark_resultados")
CLIENTE_RELATORIOS   = os.path.join(RAIZ, "cliente", "relatorios")

os.makedirs(CLIENTE_RELATORIOS,   exist_ok=True)
os.makedirs(BENCHMARK_RESULTADOS, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Layout
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Reconstrução Tomográfica",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  [data-testid="stSidebar"] { background: #1e293b; }
  .metric-card {
    background: #1e293b; border-radius: .75rem; padding: 1rem;
    text-align: center; margin-bottom: .5rem;
  }
  .metric-val { font-size: 1.8rem; font-weight: 700; color: #38bdf8; }
  .metric-lbl { font-size: .8rem; color: #94a3b8; }
  .server-badge-py  { background:#0ea5e9; color:#fff; border-radius:.5rem; padding:.2rem .6rem; font-size:.8rem; }
  .server-badge-cs  { background:#d946ef; color:#fff; border-radius:.5rem; padding:.2rem .6rem; font-size:.8rem; }
  img { border-radius: .5rem; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — configuração dos servidores
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Trabalho Final DIS")
    st.subheader("Gabriel Rodrigues Estefanes")
    st.subheader("Pedro Gabriel Fonseca")
    st.markdown("---")
    st.subheader("Servidores")
    url_python = st.text_input("Python (FastAPI)", value="http://localhost:8000")
    url_csharp = st.text_input("C# (.NET)", value="http://localhost:5001")

    st.markdown("---")

    def check_server(url, nome):
        try:
            r = requests.get(f"{url}/api/v1/health", timeout=3)
            return r.status_code < 500
        except Exception:
            try:
                requests.get(url, timeout=3)
                return True
            except Exception:
                return False

    col1, col2 = st.columns(2)
    py_ok = check_server(url_python, "Python")
    cs_ok = check_server(url_csharp, "C#")
    col1.markdown(f"{'🟢' if py_ok else '🔴'} Python")
    col2.markdown(f"{'🟢' if cs_ok else '🔴'} C#")

    if st.button("↻ Verificar"):
        st.rerun()

    st.markdown("---")
    st.caption("Desenvolvimento Integrado de Sistemas")

# ─────────────────────────────────────────────────────────────────────────────
# Abas
# ─────────────────────────────────────────────────────────────────────────────

tab_recon, tab_bench, tab_hist = st.tabs([
    "🖼️  Reconstrução ao Vivo",
    "📊  Benchmark",
    "📋  Histórico",
])

# ─────────────────────────────────────────────────────────────────────────────
# ABA 1 — Reconstrução ao vivo
# ─────────────────────────────────────────────────────────────────────────────

with tab_recon:
    st.header("Reconstrução ao Vivo")
    st.markdown("Selecione os parâmetros e clique em **Reconstruir** para enviar o mesmo sinal aos dois servidores.")

    col_cfg, col_res = st.columns([1, 2])

    with col_cfg:
        modelo_id  = st.selectbox("Modelo", [1, 2],
                                  format_func=lambda x: MODELOS[x]["label"])
        modelo     = MODELOS[modelo_id]
        sinal_nome = st.selectbox("Sinal (g)", list(modelo["sinais"].keys()))
        algoritmo  = st.selectbox("Algoritmo", ["CGNR", "CGNE"])
        usar_ganho = st.checkbox("Aplicar ganho de sinal γ")

        servidores = []
        if py_ok:
            servidores.append("Python")
        if cs_ok:
            servidores.append("C#")
        if not servidores:
            st.error("Nenhum servidor online.")
        usar_servidores = st.multiselect(
            "Enviar para", servidores, default=servidores
        )

        btn_recon = st.button("▶ Reconstruir", type="primary", use_container_width=True)

    with col_res:
        placeholder = st.empty()

    if btn_recon and usar_servidores:
        with col_cfg:
            prog = st.progress(0, text="Preparando...")

        h_path = modelo["h"]
        g_path = modelo["sinais"][sinal_nome]

        def aplicar_ganho_g(g_bytes, S, N):
            vals = [float(l.strip()) for l in g_bytes.decode().splitlines() if l.strip()]
            g = np.array(vals, dtype=np.float64)
            l_idx = np.arange(1, S + 1, dtype=np.float64)
            gamma = 100.0 + (1.0 / 20.0) * l_idx * np.sqrt(l_idx)
            g2d   = g[: S * N].reshape(S, N)
            g2d  *= gamma[:, np.newaxis]
            g[: S * N] = g2d.reshape(-1)
            return "\n".join(f"{v:.10g}" for v in g).encode()

        with open(h_path, "rb") as f:
            h_bytes = f.read()
        with open(g_path, "rb") as f:
            g_bytes_orig = f.read()

        g_bytes = aplicar_ganho_g(g_bytes_orig, modelo["S"], modelo["N"]) if usar_ganho else g_bytes_orig
        h_nome  = os.path.basename(h_path)
        g_nome  = sinal_nome

        resultados_recon = {}
        erros_recon      = {}
        url_map = {"Python": url_python, "C#": url_csharp}

        for idx, srv in enumerate(usar_servidores):
            prog.progress((idx) / len(usar_servidores), text=f"Enviando para {srv}...")
            t0 = time.perf_counter()
            try:
                resp = requests.post(
                    f"{url_map[srv]}/api/v1/reconstruct",
                    files={
                        "ArquivoMatrizCsv": (h_nome, io.BytesIO(h_bytes), "text/csv"),
                        "ArquivoSinalG":    (g_nome, io.BytesIO(g_bytes), "text/csv"),
                    },
                    data={"Algoritmo": algoritmo},
                    timeout=300,
                )
                elapsed = time.perf_counter() - t0
                body = resp.json()
                if resp.status_code == 200 and not body.get("errors"):
                    resultados_recon[srv] = {**body["data"], "tempo_s": round(elapsed, 3)}
                else:
                    erros_recon[srv] = str(body.get("errors", resp.status_code))
            except Exception as e:
                erros_recon[srv] = str(e)

        prog.progress(1.0, text="Concluído!")

        # Salvar resultado no histórico (mesmo formato do cliente.py)
        ts_hist = datetime.now().strftime("%Y%m%d_%H%M%S")
        py_res  = resultados_recon.get("Python")
        cs_res  = resultados_recon.get("C#")
        entrada_hist = [{
            "id_req":        ts_hist,
            "id_cliente":    0,
            "pixels":        modelo["pixels"],
            "algoritmo":     algoritmo,
            "ganho_aplicado": usar_ganho,
            "py_ok":         py_res is not None,
            "py_tempo_s":    py_res["tempo_s"] if py_res else None,
            "py_iteracoes":  py_res.get("iteracoesExecutadas") if py_res else None,
            "py_imagem_b64": py_res.get("imagemBase64", "") if py_res else "",
            "py_arquivo_img": f"frontend_{ts_hist}_python.png" if py_res else "",
            "cs_ok":         cs_res is not None,
            "cs_tempo_s":    cs_res["tempo_s"] if cs_res else None,
            "cs_iteracoes":  cs_res.get("iteracoesExecutadas") if cs_res else None,
        }]
        rel_path = os.path.join(CLIENTE_RELATORIOS, f"relatorio_{ts_hist}.json")
        with open(rel_path, "w", encoding="utf-8") as frel:
            json.dump(entrada_hist, frel, indent=2, ensure_ascii=False)

        with placeholder.container():
            cols = st.columns(len(usar_servidores))
            for i, srv in enumerate(usar_servidores):
                badge = "server-badge-py" if srv == "Python" else "server-badge-cs"
                with cols[i]:
                    st.markdown(f'<span class="{badge}">{srv}</span>', unsafe_allow_html=True)
                    if srv in erros_recon:
                        st.error(f"Erro: {erros_recon[srv]}")
                    else:
                        d = resultados_recon[srv]
                        b64 = d.get("imagemBase64", "")
                        if b64:
                            img = Image.open(io.BytesIO(base64.b64decode(b64)))
                            img_big = img.resize((300, 300), Image.NEAREST)
                            st.image(img_big, caption=d.get("arquivoImagem", ""), use_container_width=False)
                        else:
                            st.info("Imagem gerada (sem base64 disponível)")

                        st.metric("Tempo", f"{d['tempo_s']:.3f}s")
                        st.metric("Iterações", d.get("iteracoesExecutadas", "—"))
                        st.caption(f"Início: {d.get('inicioReconstrucao','')}")
                        st.caption(f"Fim:    {d.get('terminoReconstrucao','')}")

# ─────────────────────────────────────────────────────────────────────────────
# ABA 2 — Benchmark
# ─────────────────────────────────────────────────────────────────────────────

with tab_bench:
    st.header("Benchmark Comparativo")

    col_bcfg, col_bres = st.columns([1, 3])

    with col_bcfg:
        st.subheader("Configuração")

        bench_modelo = st.selectbox(
            "Modelo",
            options=[2, 1],
            format_func=lambda m: f"Modelo {m} ({'30×30' if m == 2 else '60×60'} px)",
            index=0,
        )

        sinais_disp = (
            {"Sinal 1 (g-30x30-1)": "1", "Sinal 2 (g-30x30-2)": "2", "Ambos": "ambos"}
            if bench_modelo == 2
            else {"Sinal 1 (g-60x60-1)": "1", "Sinal 2 (g-60x60-2)": "2", "Ambos": "ambos"}
        )
        bench_sinal = st.selectbox("Sinal", options=list(sinais_disp.keys()), index=2)
        bench_sinal_val = sinais_disp[bench_sinal]

        bench_algoritmo = st.selectbox(
            "Algoritmo",
            options=["AMBOS", "CGNR", "CGNE"],
            index=0,
        )

        bench_max_clientes = st.number_input(
            "Clientes concorrentes",
            min_value=1, max_value=32, value=3,
            help="Todos os clientes disparam simultaneamente (teste de saturação)",
        )

        bench_rodadas = st.number_input(
            "Requisições por cliente",
            min_value=1, max_value=500, value=100,
            help="Cada cliente envia este número de requests ao servidor",
        )

        total_reqs_est = bench_max_clientes * bench_rodadas
        st.caption(
            f"{bench_max_clientes} clientes × {bench_rodadas} req = "
            f"**{total_reqs_est} requests** por servidor (disparo simultâneo)"
        )

        bench_sem_cs = st.checkbox("Ignorar C#", value=not cs_ok)
        btn_bench    = st.button("▶ Rodar Benchmark", type="primary", use_container_width=True)

    bench_placeholder = col_bres.empty()

    if btn_bench:
        import subprocess

        cmd = [
            sys.executable,
            os.path.join(RAIZ, "cliente", "benchmark.py"),
            "--url-python",   url_python,
            "--url-csharp",   url_csharp,
            "--rodadas",      str(bench_rodadas),
            "--modelo",       str(bench_modelo),
            "--sinal",        bench_sinal_val,
            "--algoritmo",    bench_algoritmo,
            "--max-clientes", str(bench_max_clientes),
        ]
        if bench_sem_cs:
            cmd.append("--sem-csharp")

        total_reqs_bench = bench_max_clientes * bench_rodadas
        with bench_placeholder.container():
            st.info(
                f"Benchmark em execução — {bench_max_clientes} clientes × "
                f"{bench_rodadas} req = {total_reqs_bench} requests por servidor. Aguarde..."
            )
            prog_b = st.progress(0)
            log_area = st.empty()

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        linhas = []
        cenarios_feitos = 0
        # 1 cenário por servidor (Python + C# opcionalmente)
        total_cenarios  = 1 if bench_sem_cs else 2

        for linha in proc.stdout:
            linhas.append(linha.rstrip())
            if "✓" in linha:
                cenarios_feitos += 1
                prog_b.progress(min(cenarios_feitos / total_cenarios, 0.99))
            log_area.code("\n".join(linhas[-25:]))

        proc.wait()
        prog_b.progress(1.0)

        if proc.returncode == 0:
            st.success("Benchmark concluído!")
        else:
            st.error("Benchmark falhou. Veja o log acima para detalhes.")
            log_area.code("\n".join(linhas))
        st.rerun()

    # Exibe último benchmark disponível
    arquivos_bench = sorted(
        [f for f in os.listdir(BENCHMARK_RESULTADOS) if f.endswith(".json")]
        if os.path.isdir(BENCHMARK_RESULTADOS) else []
    )
    if arquivos_bench:
        ultimo = os.path.join(BENCHMARK_RESULTADOS, arquivos_bench[-1])
        with open(ultimo) as f:
            bdata = json.load(f)

        dados_py = bdata.get("python", [])
        dados_cs = bdata.get("csharp", [])
        ts_bench = arquivos_bench[-1].replace("benchmark_", "").replace(".json", "")

        with col_bres:
            cfg = bdata.get("config", {})
            if cfg:
                st.caption(
                    f"Modelo {cfg.get('modelo','?')} ({cfg.get('pixels','?')})  |  "
                    f"Sinal: {cfg.get('sinal','?')}  |  "
                    f"Algoritmo: {cfg.get('algoritmo','?')}  |  "
                    f"Rodadas/cliente: {cfg.get('rodadas_por_cliente','?')}"
                )
                if cfg.get("duracao_fmt"):
                    col_i, col_f, col_d = st.columns(3)
                    col_i.metric("Início", cfg.get("inicio", "—"))
                    col_f.metric("Fim",    cfg.get("fim",    "—"))
                    col_d.metric("⏱ Duração total", cfg.get("duracao_fmt", "—"))

                sys_i = cfg.get("sistema", {})
                if sys_i:
                    st.markdown(
                        f"🖥 **Sistema:** {sys_i.get('so','N/A')} &nbsp;|&nbsp; "
                        f"🧠 **CPU:** {sys_i.get('cpu_nome','N/A')} &nbsp;|&nbsp; "
                        f"⚙️ **Núcleos:** {sys_i.get('cpu_nucleos_fisicos','?')}f / {sys_i.get('cpu_nucleos_logicos','?')}l &nbsp;|&nbsp; "
                        f"⚡ **Freq. máx.:** {sys_i.get('cpu_freq_max_ghz','N/A')} GHz &nbsp;|&nbsp; "
                        f"💾 **RAM total:** {sys_i.get('ram_total_gb','N/A')} GB"
                    )
            else:
                st.caption(f"Último benchmark: {ts_bench}")

            # Tabela comparativa
            rows = []
            for dp in dados_py:
                n = dp["n_clientes"]
                dc = next((d for d in dados_cs if d["n_clientes"] == n), {})
                py_iters = f"{dp['avg_iteracoes']:.1f}" if dp.get('avg_iteracoes') is not None else "—"
                cs_iters = f"{dc['avg_iteracoes']:.1f}" if dc and dc.get('avg_iteracoes') is not None else "—"
                rows.append({
                    "Clientes": n,
                    "🐍 Throughput (img/s)": f"{dp.get('throughput', 0):.3f}",
                    "🐍 Avg (s)": f"{dp.get('avg_s', 0):.3f}",
                    "🐍 P50 (s)": f"{dp.get('p50_s', 0):.3f}",
                    "🐍 P95 (s)": f"{dp.get('p95_s', 0):.3f}",
                    "🐍 CPU %": f"{dp.get('cpu_pct', 0):.1f}%",
                    "🐍 RAM MB": f"{dp.get('ram_mb', 0):.0f}",
                    "🐍 Iterações": py_iters,
                    "⚙️ Throughput (img/s)": f"{dc.get('throughput', 0):.3f}" if dc else "—",
                    "⚙️ Avg (s)": f"{dc.get('avg_s', 0):.3f}" if dc else "—",
                    "⚙️ P95 (s)": f"{dc.get('p95_s', 0):.3f}" if dc else "—",
                    "⚙️ CPU %": f"{dc.get('cpu_pct', 0):.1f}%" if dc else "—",
                    "⚙️ RAM MB": f"{dc.get('ram_mb', 0):.0f}" if dc else "—",
                    "⚙️ Iterações": cs_iters,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.info(
                "**Como ler os resultados:**\n\n"
                "- **Throughput (img/s):** quantas imagens o servidor reconstrói por segundo — *quanto maior, melhor*\n"
                "- **Tempo Médio (avg):** média de todas as requisições — *quanto menor, melhor*\n"
                "- **Mediana (P50):** metade das requisições respondeu abaixo deste valor — representa o caso típico\n"
                "- **Pior Caso Freq. (P95):** 95% das requisições respondeu abaixo deste valor — indica estabilidade sob carga\n"
                "- **Sucesso:** requisições que completaram com sucesso vs total enviado"
            )
    else:
        with col_bres:
            st.info("Nenhum benchmark rodado ainda. Clique em **Rodar Benchmark** para começar.")

# ─────────────────────────────────────────────────────────────────────────────
# ABA 3 — Histórico
# ─────────────────────────────────────────────────────────────────────────────

with tab_hist:
    st.header("Histórico de Reconstruções")

    arquivos_rel = sorted(
        [f for f in os.listdir(CLIENTE_RELATORIOS) if f.endswith(".json")]
        if os.path.isdir(CLIENTE_RELATORIOS) else [],
        reverse=True,
    )

    if not arquivos_rel:
        st.info("Nenhum relatório gerado ainda. Use o cliente ou a aba Reconstrução.")
    else:
        sel = st.selectbox("Relatório", arquivos_rel,
                           format_func=lambda f: f.replace("relatorio_", "").replace(".json", ""))
        with open(os.path.join(CLIENTE_RELATORIOS, sel)) as f:
            rel_data = json.load(f)

        rows_hist = []
        imagens   = []
        for r in rel_data:
            rows_hist.append({
                "Req #":      r["id_req"],
                "Cliente":    f"C{r['id_cliente']}",
                "Pixels":     r["pixels"],
                "Algoritmo":  r["algoritmo"],
                "Ganho γ":    "Sim" if r["ganho_aplicado"] else "Não",
                "Python (s)": r["py_tempo_s"] if r["py_ok"] else "✗",
                "Python iter":r["py_iteracoes"] if r["py_ok"] else "—",
                "C# (s)":     r["cs_tempo_s"] if r["cs_ok"] else "✗",
                "C# iter":    r["cs_iteracoes"] if r["cs_ok"] else "—",
            })
            if r.get("py_imagem_b64"):
                imagens.append((r["id_req"], r["py_arquivo_img"], r["py_imagem_b64"]))

        st.dataframe(pd.DataFrame(rows_hist), use_container_width=True, hide_index=True)

        if imagens:
            st.subheader("Imagens reconstruídas")
            cols = st.columns(min(len(imagens), 4))
            for i, (req_id, nome, b64) in enumerate(imagens):
                with cols[i % 4]:
                    img = Image.open(io.BytesIO(base64.b64decode(b64)))
                    img_big = img.resize((200, 200), Image.NEAREST)
                    st.image(img_big, caption=f"Req #{req_id} — {nome}")
