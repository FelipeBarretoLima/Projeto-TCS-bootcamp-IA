# Rotas e esquemas (contrato da API com o frontend)

`api/schemas.py` do projeto de referência. O frontend espelha estes tipos em `src/api/tipos.ts`:
ao mudar uma resposta, mude os dois no mesmo commit.

## Sumário

1. `schemas.py`
2. Exemplos de resposta
3. Códigos HTTP usados

## 1. `schemas.py`

```python
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
    categoria: str | None = None
    origem_categoria: Literal["regra", "mapa", "modelo"] | None = None
    # como veio no extrato, sem anonimizar: só para mostrar ao dono
    historico_original: str | None = None
    contraparte_original: str | None = None


class TransacaoSalva(BaseModel):
    """Transação gravada na conta (aba Extrato). Não diz de onde veio a categoria."""
    id: int
    data: date
    historico: str
    contraparte: str
    valor: Decimal
    tipo: str
    meio: str
    banco: str
    categoria: str | None
    historico_original: str | None = None   # decifrados; None = gravada sem chave ou com outra chave
    contraparte_original: str | None = None


class PeriodoTransacoes(BaseModel):
    primeira: date | None
    ultima: date | None
    padrao_inicio: date | None  # início dos últimos 6 meses (ou a 1ª transação, se for depois)
    padrao_fim: date | None     # a última transação


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
    """Dados de um gráfico; o frontend desenha."""
    tipo: Literal["barras", "barras_horizontais", "linha", "pizza"]
    titulo: str
    rotulos: list[str]
    series: list[dict[str, Any]]
    formato: str = "moeda"


class MesDisponivel(BaseModel):
    valor: str   # "AAAA-MM"
    rotulo: str  # "mar/24"


class Painel(BaseModel):
    tem_dados: bool
    mes: str | None
    mes_valor: str | None = None
    meses: list[MesDisponivel] = []  # do mais recente ao mais antigo
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


class NovaCategoria(BaseModel):
    categoria: str | None  # uma das 8 categorias; None = sem categoria


class NovoTitulo(BaseModel):
    titulo: str = Field(min_length=1, max_length=60)


class NovoNome(BaseModel):
    nome: str = Field(min_length=1, max_length=80)


class Perfil(BaseModel):
    nome: str
    email: str
```

Na rota, declare o tipo de retorno (`-> ResultadoImportacao`): o FastAPI valida e documenta a
resposta em `/docs`.

## 2. Exemplos de resposta

`POST /api/extratos` aceito:

```json
{
  "relatorio": {"status": "aceito", "motivo": "", "parser": "nubank_conta_csv",
                "periodo_inicio": "2024-01-02", "periodo_fim": "2024-01-31",
                "linhas_extraidas": 42, "linhas_gravadas": 41, "linhas_revisar": 1,
                "linhas_duplicadas": 0, "linhas_omitidas": 0, "reconciliacao": "sem_totais"},
  "transacoes": [{"data": "2024-01-02", "historico": "COMPRA NO DÉBITO", "contraparte": "PADARIA MODELO",
                  "valor": "-12.50", "tipo": "saida", "meio": "cartao_debito", "banco": "nubank",
                  "categoria": "mercado", "origem_categoria": "modelo",
                  "historico_original": "COMPRA NO DÉBITO", "contraparte_original": "PADARIA MODELO"}],
  "sem_categoria": 0,
  "gravacao": {"extrato_id": "6f1c…", "gravadas": 38, "repetidas": 3}
}
```

`POST /api/extratos` rejeitado (status HTTP 200):

```json
{"relatorio": {"status": "rejeitado", "motivo": "ReconciliacaoFalhou", "parser": "inter_conta_pdf",
               "reconciliacao": "falhou", "...": "..."},
 "transacoes": [], "sem_categoria": 0, "gravacao": null}
```

`GET /api/painel`:

```json
{"tem_dados": true, "mes": "mar/24", "mes_valor": "2024-03",
 "meses": [{"valor": "2024-03", "rotulo": "mar/24"}, {"valor": "2024-02", "rotulo": "fev/24"}],
 "receitas": 5200.0, "despesas": 3870.45, "saldo": 1329.55,
 "grafico": {"tipo": "barras", "titulo": "Receitas x despesas (out/23 a mar/24)",
             "rotulos": ["out/23", "nov/23", "dez/23", "jan/24", "fev/24", "mar/24"],
             "series": [{"nome": "Receitas", "valores": [0, 0, 0, 0, 4800.0, 5200.0]},
                        {"nome": "Despesas", "valores": [0, 0, 0, 0, 4100.2, 3870.45]}],
             "formato": "moeda"}}
```

`POST /api/chat`:

```json
{"conversa_id": "a3b…",
 "pergunta": {"id": 10, "papel": "usuario", "texto": "Onde gastei mais?", "grafico": null,
              "criada_em": "2026-11-12T12:00:00Z"},
 "resposta": {"id": 11, "papel": "agente",
              "texto": "Em mar/24 você gastou mais com Compras (R$ 1.200,00), seguido de Mercado (R$ 950,30).",
              "grafico": {"tipo": "pizza", "titulo": "Gastos por categoria (mar/24)", "...": "..."},
              "criada_em": "2026-11-12T12:00:02Z"}}
```

Erro (qualquer rota): `{"detail": "este arquivo já foi importado"}`.

## 3. Códigos HTTP usados

| Código | Quando |
|---|---|
| 200 | sucesso (inclui extrato rejeitado pelo pipeline: o motivo está no relatório) |
| 204 | sucesso sem corpo (exclusões, correções, renomear, logout) |
| 400 | entrada inválida (formato, tamanho, vazio, período, categoria, mês, nome) |
| 401 | sem token ou token inválido/expirado (o frontend volta para o login) |
| 404 | não existe ou não é do usuário (as duas respostas são iguais de propósito) |
| 409 | mesmo arquivo já importado |
| 422 | possível dado pessoal na saída (nada devolvido); também validação do Pydantic |
| 429 | limite de uso: "muitas perguntas seguidas: espere N s e tente de novo" |
| 500 | `CHAVE_ORIGINAIS` inválida (mensagem diz como gerar) |
| 502 | o assistente (LLM) falhou; o frontend mostra o `detail` |
| 503 | serviço não configurado (banco, login ou LLM) ou login do Supabase fora do ar |
