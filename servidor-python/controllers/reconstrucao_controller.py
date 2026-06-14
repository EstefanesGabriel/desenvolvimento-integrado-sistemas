"""
ReconstrucaoController — espelho do ProcessamentoUnificadoController.cs do C#.

Endpoint:  POST /api/v1/reconstruct
Contrato (multipart/form-data — idêntico ao C#):
  - ArquivoMatrizCsv : arquivo CSV da matriz H
  - ArquivoSinalG    : arquivo CSV do sinal g  (com ganho já aplicado pelo cliente)
  - Algoritmo        : "CGNE" | "CGNR"  (default: "CGNR")

Resposta:
  {
    "data": {
      "mensagem": "...",
      "arquivoImagem": "imagem-60x60-1-CGNE.png",
      "algoritmoUtilizado": "CGNE",
      "inicioReconstrucao": "14/06/2026 15:00:00.123",
      "terminoReconstrucao": "14/06/2026 15:00:01.456",
      "tamanhoPixels": "60x60",
      "iteracoesExecutadas": 7,
      "imagemBase64": "<png em base64>"   ← extensão Python
    },
    "errors": []
  }
"""

import os
import re
import logging
from datetime import datetime

import numpy as np
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from services.matriz_service import carregar_ou_converter_matriz
from services.processamento_service import executar_cgne, executar_cgnr
from services.imagem_service import gerar_e_guardar_imagem
from viewmodels.resultado import DadosReconstrucao, ResultViewModel

logger = logging.getLogger(__name__)
router = APIRouter()

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "imagens")


def _formatar_timestamp(dt: datetime) -> str:
    """dd/MM/yyyy HH:mm:ss.mmm  — mesmo formato do C#."""
    return dt.strftime("%d/%m/%Y %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def _parse_g(conteudo: bytes) -> np.ndarray:
    """
    Lê o CSV do sinal g.
    Suporta:
      - Um valor por linha  (formato dos arquivos de teste)
      - Valores separados por vírgula ou ponto-e-vírgula por linha
    Idêntico ao StreamReader do ProcessamentoService.cs.
    """
    valores: list[float] = []
    texto = conteudo.decode("utf-8")
    for linha in texto.splitlines():
        for parte in re.split(r"[,;]", linha):
            parte = parte.strip()
            if parte:
                try:
                    valores.append(float(parte))
                except ValueError:
                    pass
    return np.array(valores, dtype=np.float64)


@router.post("/api/v1/reconstruct")
async def reconstruir(
    ArquivoMatrizCsv: UploadFile = File(..., description="CSV da matriz H"),
    ArquivoSinalG: UploadFile = File(..., description="CSV do sinal g (ganho já aplicado)"),
    Algoritmo: str = Form("CGNR", description="CGNE ou CGNR"),
):
    algoritmo = "CGNE" if Algoritmo.strip().upper() == "CGNE" else "CGNR"

    # --- Validação básica dos arquivos ---
    if not ArquivoMatrizCsv.filename:
        return JSONResponse(
            status_code=400,
            content=ResultViewModel(errors=["O arquivo CSV da Matriz H é obrigatório."]).model_dump(),
        )
    if not ArquivoSinalG.filename:
        return JSONResponse(
            status_code=400,
            content=ResultViewModel(errors=["O arquivo CSV do Sinal G é obrigatório."]).model_dump(),
        )

    # --- Carregar / cache da matriz H ---
    conteudo_h = await ArquivoMatrizCsv.read()
    try:
        H = carregar_ou_converter_matriz(conteudo_h, ArquivoMatrizCsv.filename)
    except Exception as exc:
        logger.exception("Erro ao carregar matriz H")
        return JSONResponse(
            status_code=400,
            content=ResultViewModel(errors=[f"Falha ao processar a matriz H: {exc}"]).model_dump(),
        )

    # --- Carregar sinal g ---
    conteudo_g = await ArquivoSinalG.read()
    g = _parse_g(conteudo_g)

    if g.size == 0:
        return JSONResponse(
            status_code=400,
            content=ResultViewModel(errors=["O arquivo de sinal G está vazio."]).model_dump(),
        )

    if H.shape[0] != g.size:
        return JSONResponse(
            status_code=400,
            content=ResultViewModel(
                errors=[
                    f"Dimensão incompatível: H tem {H.shape[0]} linhas, "
                    f"mas g tem {g.size} elementos."
                ]
            ).model_dump(),
        )

    # --- Extração de padrão de nome (idêntica ao C# via Regex) ---
    nome_sinal = ArquivoSinalG.filename
    match_sinal = re.search(r"\d+x\d+-\d+", nome_sinal)
    if not match_sinal:
        match_sinal = re.search(r"\d+x\d+", nome_sinal)
    if not match_sinal:
        return JSONResponse(
            status_code=400,
            content=ResultViewModel(
                errors=["O nome do arquivo de sinal deve conter o padrão de dimensão (ex: g-60x60-1.csv)."]
            ).model_dump(),
        )

    sufixo_sinal = match_sinal.group()                    # ex: "60x60-1"
    nome_imagem = f"imagem-{sufixo_sinal}-{algoritmo}.png"

    match_dim = re.search(r"(\d+)x(\d+)", sufixo_sinal)
    largura = int(match_dim.group(1))
    altura  = int(match_dim.group(2))
    str_pixels = f"{largura}x{altura}"

    # --- Cache da imagem final ---
    caminho_imagem_final = os.path.join(OUTPUT_DIR, nome_imagem)
    if os.path.exists(caminho_imagem_final):
        import base64
        with open(caminho_imagem_final, "rb") as fp:
            img_b64 = base64.b64encode(fp.read()).decode("utf-8")
        dados = DadosReconstrucao(
            mensagem="Imagem recuperada do cache com sucesso! (Processamento matemático pulado)",
            arquivoImagem=nome_imagem,
            algoritmoUtilizado=algoritmo,
            inicioReconstrucao="N/A (Recuperado do Cache)",
            terminoReconstrucao="N/A (Recuperado do Cache)",
            tamanhoPixels=str_pixels,
            iteracoesExecutadas=0,
            imagemBase64=img_b64,
        )
        return ResultViewModel(data=dados.model_dump(), errors=[])

    # --- Execução do algoritmo ---
    try:
        inicio = datetime.now()
        if algoritmo == "CGNE":
            resultado = executar_cgne(H, g)
        else:
            resultado = executar_cgnr(H, g)
        termino = datetime.now()
    except Exception as exc:
        logger.exception("Erro no algoritmo %s", algoritmo)
        return JSONResponse(
            status_code=500,
            content=ResultViewModel(
                errors=[f"Erro matemático ao processar {algoritmo}: {exc}"]
            ).model_dump(),
        )

    # --- Geração e gravação da imagem ---
    try:
        nome_arq, img_b64 = gerar_e_guardar_imagem(
            resultado.vetor_f, largura, altura, nome_imagem
        )
    except Exception as exc:
        logger.exception("Erro ao gerar imagem")
        return JSONResponse(
            status_code=500,
            content=ResultViewModel(errors=[f"Erro ao gerar imagem: {exc}"]).model_dump(),
        )

    dados = DadosReconstrucao(
        mensagem="Processamento completo e imagem gerada com sucesso!",
        arquivoImagem=nome_arq,
        algoritmoUtilizado=algoritmo,
        inicioReconstrucao=_formatar_timestamp(inicio),
        terminoReconstrucao=_formatar_timestamp(termino),
        tamanhoPixels=str_pixels,
        iteracoesExecutadas=resultado.iteracoes,
        imagemBase64=img_b64,
    )

    return ResultViewModel(data=dados.model_dump(), errors=[])
