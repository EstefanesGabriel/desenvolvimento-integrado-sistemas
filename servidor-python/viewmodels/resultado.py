from pydantic import BaseModel
from typing import Optional, List, Any


class DadosReconstrucao(BaseModel):
    mensagem: str
    arquivoImagem: str
    algoritmoUtilizado: str
    inicioReconstrucao: str
    terminoReconstrucao: str
    tamanhoPixels: str
    iteracoesExecutadas: int
    imagemBase64: Optional[str] = None


class ResultViewModel(BaseModel):
    data: Optional[Any] = None
    errors: List[str] = []
