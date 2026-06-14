"""
ProcessamentoService — espelho do ProcessamentoService.cs do C#.

Implementa CGNE e CGNR com paridade 1-a-1 com a versão C#:
  - f0 = 0
  - Parada: ||r|| < tol  OU  i == max_iter
  - Mesmo cálculo de alpha, beta, p e z/r

Nota sobre o ganho de sinal (γ):
  O ganho É APLICADO PELO CLIENTE antes de enviar o sinal g.
  O servidor recebe g já com ganho aplicado — igual ao C#.
"""

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp


@dataclass
class ResultadoAlgoritmo:
    vetor_f: np.ndarray
    iteracoes: int


# ---------------------------------------------------------------------------
# CGNE — Conjugate Gradient Normal Error
# ---------------------------------------------------------------------------

def executar_cgne(
    H: sp.csr_matrix,
    g: np.ndarray,
    max_iter: int = 10,
    tol: float = 1e-4,
) -> ResultadoAlgoritmo:
    """
    f0  = 0
    r0  = g - H·f0  →  r0 = g
    p0  = H^T · r0

    loop:
      alpha_i = (r^T·r) / (p^T·p)
      f_{i+1} = f_i + alpha_i · p_i
      r_{i+1} = r_i - alpha_i · H·p_i
      beta_i  = (r_{i+1}^T·r_{i+1}) / (r_i^T·r_i)
      p_{i+1} = H^T · r_{i+1} + beta_i · p_i
    """
    f = np.zeros(H.shape[1], dtype=np.float64)
    r = g.astype(np.float64).copy()
    p = H.T @ r  # scipy sparse × dense = dense

    norm_r_sq = float(r @ r)
    iteracoes = 0

    for i in range(max_iter):
        iteracoes = i + 1

        norm_p_sq = float(p @ p)
        if norm_p_sq == 0.0:
            break

        alpha = norm_r_sq / norm_p_sq
        f = f + alpha * p

        Hp = H @ p
        r = r - alpha * Hp

        if np.linalg.norm(r) < tol:
            break

        norm_r_new_sq = float(r @ r)
        if norm_r_sq == 0.0:
            break

        beta = norm_r_new_sq / norm_r_sq
        HTr = H.T @ r
        p = HTr + beta * p
        norm_r_sq = norm_r_new_sq

    return ResultadoAlgoritmo(vetor_f=f, iteracoes=iteracoes)


# ---------------------------------------------------------------------------
# CGNR — Conjugate Gradient Normal Residual  (Saad2003, p. 266)
# ---------------------------------------------------------------------------

def executar_cgnr(
    H: sp.csr_matrix,
    g: np.ndarray,
    max_iter: int = 10,
    tol: float = 1e-4,
) -> ResultadoAlgoritmo:
    """
    f0  = 0
    r0  = g - H·f0  →  r0 = g
    z0  = H^T · r0
    p0  = z0

    loop:
      w_i    = H · p_i
      alpha_i = ||z_i||^2 / ||w_i||^2
      f_{i+1} = f_i + alpha_i · p_i
      r_{i+1} = r_i - alpha_i · w_i
      z_{i+1} = H^T · r_{i+1}
      beta_i  = ||z_{i+1}||^2 / ||z_i||^2
      p_{i+1} = z_{i+1} + beta_i · p_i
    """
    f = np.zeros(H.shape[1], dtype=np.float64)
    r = g.astype(np.float64).copy()
    z = H.T @ r
    p = z.copy()

    norm_z_sq = float(z @ z)
    iteracoes = 0

    for i in range(max_iter):
        iteracoes = i + 1

        w = H @ p
        norm_w_sq = float(w @ w)
        if norm_w_sq == 0.0:
            break

        alpha = norm_z_sq / norm_w_sq
        f = f + alpha * p
        r = r - alpha * w

        if np.linalg.norm(r) < tol:
            break

        z_new = H.T @ r
        norm_z_new_sq = float(z_new @ z_new)
        if norm_z_sq == 0.0:
            break

        beta = norm_z_new_sq / norm_z_sq
        p = z_new + beta * p
        norm_z_sq = norm_z_new_sq

    return ResultadoAlgoritmo(vetor_f=f, iteracoes=iteracoes)
