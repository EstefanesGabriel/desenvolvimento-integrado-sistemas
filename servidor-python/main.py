"""
Servidor Python — Reconstrução de Imagens Tomográficas
======================================================

Versão interpretada / fracamente tipada do servidor de reconstrução.
Espelha o servidor C# (desenvolvimento-integrado-sistemas) com o
mesmo contrato de API, permitindo que um único cliente envie os
mesmos sinais para os dois servidores.

Endpoints:
  GET  /api/v1/health      → health-check
  POST /api/v1/reconstruct → reconstrução via CGNE ou CGNR

Execução:
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from controllers.reconstrucao_controller import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="Servidor Python — Reconstrução de Imagens",
    description=(
        "Versão Python (interpretada/fracamente tipada) do servidor de "
        "reconstrução tomográfica. Algoritmos: CGNE e CGNR."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/api/v1/health", tags=["health"])
def health():
    """Health-check — confirma que o servidor Python está no ar."""
    return {
        "status": "ok",
        "servidor": "Python (FastAPI + Uvicorn)",
        "algoritmos_suportados": ["CGNE", "CGNR"],
    }
