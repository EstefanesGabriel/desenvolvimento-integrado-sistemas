"""
MatrizService — espelho do MatrizService.cs do C#.

Responsabilidade:
  - Receber o conteúdo bruto do CSV da matriz H.
  - Converter para scipy.sparse.csr_matrix.
  - Fazer cache em disco (.npz) com o mesmo critério do C# (nome do arquivo
    de origem como chave de cache) para não reprocessar a matriz gigante a
    cada requisição.
"""

import io
import os
import logging

import numpy as np
import scipy.sparse as sp

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache")


def _caminho_cache(nome_arquivo_csv: str) -> str:
    nome_base = os.path.splitext(os.path.basename(nome_arquivo_csv))[0]
    return os.path.join(CACHE_DIR, f"{nome_base}-convertida.npz")


def _csv_para_esparsa(conteudo: bytes) -> sp.csr_matrix:
    """Converte CSV de H para matriz esparsa — mesma lógica do MatrizService.cs."""
    rows: list[int] = []
    cols: list[int] = []
    vals: list[float] = []
    n_rows = 0
    n_cols = 0

    stream = io.TextIOWrapper(io.BytesIO(conteudo), encoding="utf-8")
    for linha in stream:
        linha = linha.strip()
        if not linha:
            continue
        partes = linha.split(",")
        if n_rows == 0:
            n_cols = len(partes)
        for j, v in enumerate(partes):
            v = v.strip()
            if not v:
                continue
            try:
                val = float(v)
                if val != 0.0:
                    rows.append(n_rows)
                    cols.append(j)
                    vals.append(val)
            except ValueError:
                pass
        n_rows += 1

    if n_rows == 0 or n_cols == 0:
        raise ValueError("CSV da matriz H está vazio ou mal formatado.")

    matriz = sp.csr_matrix(
        (np.array(vals, dtype=np.float64),
         (np.array(rows, dtype=np.int32), np.array(cols, dtype=np.int32))),
        shape=(n_rows, n_cols),
    )
    return matriz


def carregar_ou_converter_matriz(conteudo: bytes, nome_arquivo: str) -> sp.csr_matrix:
    """
    Retorna a matriz H pronta.
    - Se o cache .npz já existir para este nome de arquivo, carrega diretamente.
    - Caso contrário, converte o CSV, salva o cache e retorna.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    caminho_cache = _caminho_cache(nome_arquivo)

    if os.path.exists(caminho_cache):
        logger.info("Cache encontrado: carregando %s", caminho_cache)
        return sp.load_npz(caminho_cache)

    logger.info("Cache não encontrado — convertendo CSV '%s'...", nome_arquivo)
    matriz = _csv_para_esparsa(conteudo)
    sp.save_npz(caminho_cache, matriz)
    logger.info("Cache salvo em %s  (shape=%s)", caminho_cache, matriz.shape)
    return matriz
