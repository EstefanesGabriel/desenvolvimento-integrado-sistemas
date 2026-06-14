"""
ImagemService — espelho do ImageService.cs do C#.

- Normaliza o vetor f para 0-255.
- Usa exatamente o mesmo mapeamento column-major que o C#:
      index = x * altura + y   →   image[x, y]
  (em numpy: img_array[y, x] = f[x * altura + y])
- Salva PNG em disco.
- Retorna o nome do arquivo e o conteúdo em base64.
"""

import base64
import os
from typing import Tuple

import numpy as np
from PIL import Image

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "imagens")


def gerar_e_guardar_imagem(
    f: np.ndarray,
    largura: int,
    altura: int,
    nome_arquivo: str,
) -> Tuple[str, str]:
    """
    Parâmetros
    ----------
    f            : vetor f reconstruído (tamanho = largura * altura)
    largura      : largura da imagem em pixels
    altura       : altura da imagem em pixels
    nome_arquivo : nome do arquivo PNG de saída

    Retorna
    -------
    (nome_arquivo, base64_string)
    """
    if len(f) != largura * altura:
        raise ValueError(
            f"Vetor f tem {len(f)} elementos, mas esperado {largura * altura} "
            f"({largura}x{altura})."
        )

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    f_min = float(f.min())
    f_max = float(f.max())
    f_range = f_max - f_min if f_max != f_min else 1.0

    # --- mapeamento column-major idêntico ao C# ---
    # C#: index = x * altura + y  →  image[x, y]
    # numpy: img_array[y, x] = f[x * altura + y]
    x_idx = np.arange(largura, dtype=np.int32).reshape(1, -1)   # (1, largura)
    y_idx = np.arange(altura,  dtype=np.int32).reshape(-1, 1)   # (altura, 1)
    f_indices = x_idx * altura + y_idx                          # (altura, largura)

    img_array = ((f[f_indices] - f_min) / f_range * 255.0).clip(0, 255).astype(np.uint8)

    img = Image.fromarray(img_array, mode="L")
    caminho = os.path.join(OUTPUT_DIR, nome_arquivo)
    img.save(caminho)

    with open(caminho, "rb") as fp:
        img_b64 = base64.b64encode(fp.read()).decode("utf-8")

    return nome_arquivo, img_b64
