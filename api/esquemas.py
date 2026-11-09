"""Formato das respostas da API (contrato com o frontend)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Saude(BaseModel):
    status: str


class ConfigPublica(BaseModel):
    supabase_url: str
    supabase_publishable_key: str


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
    origem_categoria: Literal["regra", "mapa", "modelo"] | None = None


class TransacaoSalva(BaseModel):
    """Transação gravada na conta do usuário (aba Extrato). Não diz de onde veio a categoria."""

    data: date
    historico: str
    contraparte: str
    valor: Decimal
    tipo: str
    meio: str
    banco: str
    categoria: str | None


class PeriodoTransacoes(BaseModel):
    """Datas das transações do usuário e o filtro padrão da aba Extrato (None = nenhuma transação)."""

    primeira: date | None
    ultima: date | None
    padrao_inicio: date | None  # início dos últimos 6 meses (ou a 1ª transação, se for depois)
    padrao_fim: date | None  # a última transação


class ResultadoUpload(BaseModel):
    relatorio: Relatorio
    transacoes: list[Transacao]
    sem_categoria: int = 0


class Gravacao(BaseModel):
    """O que entrou no banco: as repetidas já estavam lá (extratos com períodos sobrepostos)."""

    extrato_id: UUID
    gravadas: int
    repetidas: int


class ResultadoImportacao(ResultadoUpload):
    gravacao: Gravacao | None = None  # None = extrato rejeitado, nada gravado


class ExtratoEnviado(BaseModel):
    id: UUID
    nome_arquivo: str
    banco: str
    parser: str
    periodo_inicio: date | None
    periodo_fim: date | None
    linhas_gravadas: int
    enviado_em: datetime


class Grafico(BaseModel):
    """Dados de um gráfico; o frontend desenha (ver agente/consultas.py)."""

    tipo: Literal["barras", "barras_horizontais", "linha", "pizza"]
    titulo: str
    rotulos: list[str]
    series: list[dict[str, Any]]
    formato: str = "moeda"


class Painel(BaseModel):
    tem_dados: bool
    mes: str | None
    receitas: float
    despesas: float
    saldo: float
    grafico: Grafico | None


class Conversa(BaseModel):
    id: UUID
    titulo: str
    criada_em: datetime
    atualizada_em: datetime


class Mensagem(BaseModel):
    id: int
    papel: Literal["usuario", "agente"]
    texto: str
    grafico: Grafico | None = None
    criada_em: datetime


class Pergunta(BaseModel):
    mensagem: str = Field(min_length=1, max_length=1000)
    conversa_id: UUID | None = None  # None = começa uma conversa nova


class RespostaChat(BaseModel):
    conversa_id: UUID
    pergunta: Mensagem
    resposta: Mensagem
