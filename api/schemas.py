"""Shape of the API responses (contract with the frontend).

Only the class names are in English: the fields become the JSON the frontend reads, so they stay
in Portuguese.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Health(BaseModel):
    status: str


class PublicConfig(BaseModel):
    supabase_url: str
    supabase_publishable_key: str


class Report(BaseModel):
    """Processing summary. Only counts and codes, nothing from the statement content."""

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


class Transaction(BaseModel):
    """An already anonymized and validated row (same contract as the parser CSV)."""

    data: date
    historico: str
    contraparte: str
    valor: Decimal  # goes in the JSON as text ("-12.34") so no precision is lost
    tipo: str
    meio: str
    banco: str
    categoria: str | None = None  # one of the 8 classes in ml/classes.py; None = uncategorized
    origem_categoria: Literal["regra", "mapa", "modelo"] | None = None
    # as it came in the statement, not anonymized: only to show the owner (ML and chat use the fields above)
    historico_original: str | None = None
    contraparte_original: str | None = None


class SavedTransaction(BaseModel):
    """Transaction saved in the user's account (Extrato tab). It does not say where the category came from."""

    id: int
    data: date
    historico: str
    contraparte: str
    valor: Decimal
    tipo: str
    meio: str
    banco: str
    categoria: str | None
    # decrypted from the database; None = saved without a key or with another key (shows the anonymized text)
    historico_original: str | None = None
    contraparte_original: str | None = None


class TransactionPeriod(BaseModel):
    """Dates of the user's transactions and the default filter of the Extrato tab (None = no transactions)."""

    primeira: date | None
    ultima: date | None
    padrao_inicio: date | None  # start of the last 6 months (or the 1st transaction, if later)
    padrao_fim: date | None  # the last transaction


class UploadResult(BaseModel):
    relatorio: Report
    transacoes: list[Transaction]
    sem_categoria: int = 0


class SaveSummary(BaseModel):
    """What went into the database: the duplicates were already there (statements with overlapping periods)."""

    extrato_id: UUID
    gravadas: int
    repetidas: int


class ImportResult(UploadResult):
    gravacao: SaveSummary | None = None  # None = statement rejected, nothing saved


class UploadedStatement(BaseModel):
    id: UUID
    nome_arquivo: str
    banco: str
    parser: str
    periodo_inicio: date | None
    periodo_fim: date | None
    linhas_gravadas: int
    enviado_em: datetime


class Chart(BaseModel):
    """Data of a chart; the frontend draws it (see agent/queries.py)."""

    tipo: Literal["barras", "barras_horizontais", "linha", "pizza"]
    titulo: str
    rotulos: list[str]
    series: list[dict[str, Any]]
    formato: str = "moeda"


class AvailableMonth(BaseModel):
    valor: str  # "YYYY-MM"
    rotulo: str  # "mar/24"


class Dashboard(BaseModel):
    tem_dados: bool
    mes: str | None
    mes_valor: str | None = None  # the month shown, "YYYY-MM"
    meses: list[AvailableMonth] = []  # months with transactions, from the most recent to the oldest
    receitas: float
    despesas: float
    saldo: float
    grafico: Chart | None


class Conversation(BaseModel):
    id: UUID
    titulo: str
    criada_em: datetime
    atualizada_em: datetime


class Message(BaseModel):
    id: int
    papel: Literal["usuario", "agente"]
    texto: str
    grafico: Chart | None = None
    criada_em: datetime


class Question(BaseModel):
    mensagem: str = Field(min_length=1, max_length=1000)
    conversa_id: UUID | None = None  # None = starts a new conversation


class ChatAnswer(BaseModel):
    conversa_id: UUID
    pergunta: Message
    resposta: Message


class Transcription(BaseModel):
    texto: str  # what was said in the audio; the user checks it before sending it as a question


class NewCategory(BaseModel):
    categoria: str | None  # one of the 8 categories; None = uncategorized


class NewTitle(BaseModel):
    titulo: str = Field(min_length=1, max_length=60)


class NewName(BaseModel):
    nome: str = Field(min_length=1, max_length=80)


class Profile(BaseModel):
    nome: str
    email: str
