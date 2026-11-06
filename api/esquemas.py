"""Formato das respostas da API (contrato com o frontend)."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class Saude(BaseModel):
    status: str


class Relatorio(BaseModel):
    """Resumo do processamento. Só contagens e códigos, nada do conteúdo do extrato."""

    status: str  # "aceito" | "rejeitado"
    motivo: str
    parser: str
    periodo_inicio: str
    periodo_fim: str
    linhas_extraidas: int
    linhas_gravadas: int
    linhas_revisar: int
    linhas_duplicadas: int
    linhas_omitidas: int
    reconciliacao: str


class Transacao(BaseModel):
    """Uma linha já anonimizada e validada (mesmo contrato do CSV do parser)."""

    data: date
    historico: str
    contraparte: str
    valor: Decimal  # vai no JSON como texto ("-12.34") para não perder precisão
    tipo: str
    meio: str
    banco: str
    categoria: str | None = None  # uma das 8 classes de ml/classes.py; None = sem categoria
    origem_categoria: Literal["regra", "mapa"] | None = None


class ResultadoUpload(BaseModel):
    relatorio: Relatorio
    transacoes: list[Transacao]
    sem_categoria: int = 0
