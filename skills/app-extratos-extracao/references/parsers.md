# Parsers: interface, registro, conferência, exemplos e testes

Código do projeto de referência (`extraction/src/statement/parsers/`). Copie a estrutura e
adapte os layouts aos extratos reais do usuário.

## Sumário

1. `parsers/base.py`: interface e tipos
2. `parsers/registry.py`: escolha do parser
3. `reconciliation.py`: conferência dos totais
4. Exemplo completo: CSV da conta do Nubank
5. Exemplo completo: PDF com saldo após cada lançamento (conta do Inter)
6. Outros padrões de layout
7. Testes

## 1. `parsers/base.py`

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal

from ..models import PaymentMethod


class ExtractionError(Exception):
    """Base dos erros do pipeline. A mensagem nunca leva conteúdo do extrato."""
    code = "ErroExtracao"  # código estável: vai para o relatório/API


class UnrecognizedFormat(ExtractionError):
    code = "FormatoNaoReconhecido"


class AmbiguousFormat(ExtractionError):
    code = "FormatoAmbiguo"


class UnexpectedLayout(ExtractionError):
    """Algo fora do layout que o parser conhece. Só código + página."""
    code = "LayoutInesperado"

    def __init__(self, parser: str, motivo: str, page: int | None = None):
        where = f" (página {page})" if page is not None else ""
        super().__init__(f"parser {parser}: {motivo}{where}")
        self.motivo = motivo
        self.page = page


class UnknownHistory(ExtractionError):
    code = "HistoricoDesconhecido"

    def __init__(self, parser: str, historico: str):
        # o histórico fica no atributo (vai para data/privado), não na mensagem
        super().__init__(f"parser {parser}: histórico fora do mapa explícito")
        self.parser = parser
        self.historico = historico


@dataclass(frozen=True)
class RawTransaction:
    """Lançamento como lido do documento. Vive só em memória.

    historico: o tipo do lançamento (ex.: "PIX ENVIADO"), sem o complemento.
    contraparte / counterparty_document: nome e CPF/CNPJ da outra parte, se o layout tiver.
    segment: índice (ou índices) em ExtractionResult.segmentos usados na conferência.
    page: só para mensagens de erro.
    """

    data: date
    historico: str
    valor: Decimal
    segment: int | tuple[int, ...]
    contraparte: str = ""
    counterparty_document: str = ""
    page: int | None = None
    review_reason: str = ""   # o parser não garante a anonimização: a linha vai para revisão
    duplicate: bool = False   # cópia que o documento repete: entra na conferência, não na saída
    omitted: bool = False     # não é movimento novo (ex.: pagamento da fatura dentro da fatura)


@dataclass(frozen=True)
class Segment:
    """Trecho com totais declarados: opening + soma(valores) == closing.

    conta:  opening = saldo anterior, closing = saldo final (ou do dia);
    fatura: opening = -saldo da fatura anterior (0 se não houver), closing = -total da fatura.
    """

    label: str          # sem dado pessoal: "fatura 2025-03", "dia 2024-01-05"
    opening: Decimal
    closing: Decimal
    document: str = ""  # documento independente dentro do arquivo (só com REJECT_BY_DOCUMENT)


@dataclass
class ExtractionResult:
    banco: str
    product: Literal["conta", "cartao"]
    transactions: list[RawTransaction]
    segmentos: list[Segment]
    holder_names: list[str] = field(default_factory=list)  # titular + portadores/adicionais


class Parser(ABC):
    name: ClassVar[str]                     # "bradesco_conta_pdf"
    banco: ClassVar[str]                    # slug do contrato
    product: ClassVar[Literal["conta", "cartao"]]
    METHODS: ClassVar[Mapping[str, PaymentMethod]]  # histórico normalizado -> meio. Fora = erro
    NO_TOTALS: ClassVar[bool] = False       # só formatos sem nenhum saldo/total (aceito como "sem_totais")
    REJECT_BY_DOCUMENT: ClassVar[bool] = False  # arquivo com vários documentos: rejeita só o que não bate

    @classmethod
    @abstractmethod
    def detect(cls, path: Path) -> bool:
        """True se o arquivo tem a assinatura deste formato. Não pode levantar exceção."""

    @abstractmethod
    def extract(self, path: Path) -> ExtractionResult:
        """Lê o arquivo inteiro. Qualquer coisa fora do layout esperado é erro."""

    @classmethod
    def method_for(cls, normalized_history: str) -> PaymentMethod:
        try:
            return cls.METHODS[normalized_history]
        except KeyError:
            raise UnknownHistory(cls.name, normalized_history) from None


@lru_cache(maxsize=32)
def pdf_text(path: Path, max_pages: int | None = None) -> tuple[str, ...]:
    """Texto de cada página (pdfplumber). Tupla vazia se não for um PDF legível."""
    import pdfplumber

    try:
        with pdfplumber.open(path) as pdf:
            pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
            return tuple(p.extract_text() or "" for p in pages)
    except Exception:  # noqa: BLE001 - detect() não pode falhar
        return ()


@lru_cache(maxsize=32)
def first_line(path: Path, encoding: str = "utf-8-sig") -> str:
    """Primeira linha do arquivo de texto ('' se não der para ler)."""
    try:
        with open(path, encoding=encoding, newline="") as f:
            return f.readline().rstrip("\r\n")
    except (OSError, UnicodeDecodeError):
        return ""
```

Os caches existem porque vários parsers olham o mesmo arquivo em `detect`. Num servidor, chame
`pdf_text.cache_clear()` e `first_line.cache_clear()` depois de cada processamento.

## 2. `parsers/registry.py`

```python
from .base import AmbiguousFormat, UnrecognizedFormat, Parser
from .nubank_conta_csv import NubankAccountCsv
from .inter_conta_pdf import InterAccountPdf
# ... um import por formato

PARSERS: list[type[Parser]] = [InterAccountPdf, NubankAccountCsv]  # um por formato do inventário


def choose_parser(path, parsers=None) -> Parser:
    candidates = PARSERS if parsers is None else parsers
    recognizers = [p for p in candidates if p.detect(path)]
    if not recognizers:
        raise UnrecognizedFormat("nenhum parser reconhece o arquivo")
    if len(recognizers) > 1:
        names = ", ".join(sorted(p.name for p in recognizers))
        raise AmbiguousFormat(f"mais de um parser reconhece o arquivo: {names}")
    return recognizers[0]()
```

## 3. `reconciliation.py`

```python
from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import Decimal

from .parsers.base import ExtractionError, ExtractionResult


class ReconciliationFailed(ExtractionError):
    code = "ReconciliacaoFalhou"

    def __init__(self, divergent: int, total: int, motivo: str = "soma não bate com o total declarado"):
        super().__init__(f"{motivo}: {divergent} de {total} segmento(s)")
        self.divergent, self.total = divergent, total


@dataclass(frozen=True)
class ReconciliationStatus:
    segmentos: int
    divergent: int

    @property
    def ok(self) -> bool:
        return self.segmentos > 0 and self.divergent == 0


def _indices(t) -> tuple[int, ...]:
    return t.segment if isinstance(t.segment, tuple) else (t.segment,)


def check(result: ExtractionResult) -> ReconciliationStatus:
    """Calcula o status sem levantar exceção. Índice de segmento inexistente conta como divergente."""
    running_sum: dict[int, Decimal] = defaultdict(Decimal)
    for t in result.transactions:
        for idx in _indices(t):
            running_sum[idx] += t.valor
    n = len(result.segmentos)
    orphans = sum(1 for idx in running_sum if not 0 <= idx < n)
    divergent = orphans + sum(1 for i, s in enumerate(result.segmentos)
                              if s.opening + running_sum[i] != s.closing)
    return ReconciliationStatus(segmentos=n, divergent=divergent)


def reconcile(result: ExtractionResult) -> ReconciliationStatus:
    """Como `check`, mas rejeita o arquivo se algo não bater."""
    if not result.segmentos:
        raise ReconciliationFailed(0, 0, "documento sem totais declarados")
    status = check(result)
    if not status.ok:
        raise ReconciliationFailed(status.divergent, status.segmentos)
    return status


def split_divergent_documents(result: ExtractionResult) -> tuple[ExtractionResult, list[str]]:
    """Para REJECT_BY_DOCUMENT: devolve (só os documentos que batem, documentos rejeitados).

    Exige `document` em todo segmento e nenhum lançamento misturando documentos.
    """
    n = len(result.segmentos)
    if not n or any(not s.document for s in result.segmentos):
        raise ReconciliationFailed(0, n, "segmento sem documento")
    running_sum: dict[int, Decimal] = defaultdict(Decimal)
    for t in result.transactions:
        idx = _indices(t)
        if any(not 0 <= i < n for i in idx) or len({result.segmentos[i].document for i in idx}) > 1:
            raise ReconciliationFailed(1, n, "lançamento fora de segmento ou em dois documentos")
        for i in idx:
            running_sum[i] += t.valor
    bad = sorted({s.document for i, s in enumerate(result.segmentos)
                  if s.opening + running_sum[i] != s.closing})
    if not bad:
        return result, []
    keep = [i for i, s in enumerate(result.segmentos) if s.document not in bad]
    new_index = {old: new for new, old in enumerate(keep)}
    transactions = [replace(t, segment=tuple(new_index[i] for i in _indices(t)))
                    for t in result.transactions
                    if not any(result.segmentos[i].document in bad for i in _indices(t))]
    return replace(result, transactions=transactions, segmentos=[result.segmentos[i] for i in keep]), bad
```

No pipeline: `NO_TOTALS` → reconciliação `sem_totais` (e rejeita se o parser devolveu segmentos);
senão, `split_divergent_documents` (se `REJECT_BY_DOCUMENT`) e depois `reconcile`.

## 4. Exemplo completo: CSV da conta do Nubank

O app do Nubank exporta `Data,Valor,Identificador,Descrição`, sem saldo nem total. É o formato mais
simples para começar. O vocabulário fica num módulo próprio porque o PDF da mesma conta usa os
mesmos tipos.

`parsers/nubank_common.py` (os tipos já vistos em extratos reais; tipo novo = `UnknownHistory`):

```python
import re
from dataclasses import dataclass
from typing import Literal

from ..models import PaymentMethod
from ..normalization import normalize_history

Rule = Literal["transferencia", "estabelecimento", "beneficiario", "estorno", "nenhuma"]


@dataclass(frozen=True)
class NubankType:
    meio: PaymentMethod
    sign: int          # -1 sempre saída, +1 sempre entrada
    contraparte: Rule  # de onde vem a contraparte


# texto exatamente como o Nubank escreve (maiúsculas/minúsculas importam)
TYPES: dict[str, NubankType] = {
    "Transferência enviada pelo Pix": NubankType(PaymentMethod.PIX, -1, "transferencia"),
    "Transferência recebida pelo Pix": NubankType(PaymentMethod.PIX, +1, "transferencia"),
    "Transferência Recebida": NubankType(PaymentMethod.TED_DOC, +1, "transferencia"),
    "Reembolso recebido pelo Pix": NubankType(PaymentMethod.REFUND, +1, "transferencia"),
    "Compra no débito via NuPay": NubankType(PaymentMethod.DEBIT_CARD, -1, "estabelecimento"),
    "Compra no débito": NubankType(PaymentMethod.DEBIT_CARD, -1, "estabelecimento"),
    "Pagamento de boleto efetuado": NubankType(PaymentMethod.BANK_SLIP, -1, "beneficiario"),
    "Depósito Recebido por Boleto": NubankType(PaymentMethod.BANK_SLIP, +1, "nenhuma"),
    "Pagamento de fatura": NubankType(PaymentMethod.INVOICE_PAYMENT, -1, "nenhuma"),
    "Aplicação RDB": NubankType(PaymentMethod.INVESTMENT, -1, "nenhuma"),
    "Resgate RDB": NubankType(PaymentMethod.INVESTMENT, +1, "nenhuma"),
    "Valor adicionado na conta por cartão de crédito": NubankType(PaymentMethod.CREDIT_CARD, +1, "nenhuma"),
    "Recarga de celular": NubankType(PaymentMethod.OTHER, -1, "nenhuma"),
    "Crédito em conta": NubankType(PaymentMethod.OTHER, +1, "nenhuma"),
    "Estorno": NubankType(PaymentMethod.REFUND, +1, "estorno"),
}

METHODS = {normalize_history(k): t.meio for k, t in TYPES.items()}
_ORDER = sorted(TYPES, key=len, reverse=True)  # "Compra no débito via NuPay" antes de "Compra no débito"

_DOC = (r"(?P<doc>•••\.\s*\d{3}\.\s*\d{3}\s*-\s*••"          # CPF mascarado
        r"|\d{2}\.\s*\d{3}\.\s*\d{3}\s*/\s*\d{4}\s*-\s*\d{2})")  # CNPJ
_TRANSFER = re.compile(r"^(?:-\s+)?(?P<nome>.+?)\s+-\s+" + _DOC + r"(?:\s+-\s+.*)?$")
_TRANSFER_NAME_ONLY = re.compile(r"^(?P<nome>(?:(?! - )[^()\d])+?)(?: \(Transferência enviada\))?$")


class InvalidComplement(ValueError):
    code = "ComplementoInvalido"


def split_type(description: str) -> tuple[str, str]:
    """('Compra no débito', 'LOJA X') ou (descrição, '') se o tipo não for conhecido."""
    for tipo in _ORDER:
        if description == tipo:
            return tipo, ""
        if description.startswith(tipo + " "):
            return tipo, description[len(tipo):].strip()
    return description, ""


def contraparte(tipo: str, complement: str) -> tuple[str, str]:
    """(nome, documento) da contraparte, conforme a regra do tipo."""
    rule = TYPES[tipo].contraparte if tipo in TYPES else "nenhuma"
    rest = re.sub(r"^-\s+", "", complement).strip()
    if rule == "nenhuma":
        return "", ""
    if rule == "transferencia":
        m = _TRANSFER.match(complement)
        if m:
            return m["nome"].strip(), re.sub(r"\s+", "", m["doc"])
        m = _TRANSFER_NAME_ONLY.match(rest)
        if m and tipo == "Transferência enviada pelo Pix":
            return m["nome"].strip(), ""
        raise InvalidComplement("transferencia_sem_documento")
    if rule == "estorno":  # "Estorno - Compra no débito - LOJA": o estabelecimento é a última parte
        sub_type, sub_rest = split_type(rest)
        if sub_type in TYPES:
            rest = re.sub(r"^-\s+", "", sub_rest).strip()
    if not rest:
        raise InvalidComplement(f"{rule}_vazio")
    return rest, ""
```

`parsers/nubank_conta_csv.py`:

```python
import csv
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from . import nubank_common as nu
from .base import UnexpectedLayout, Parser, ExtractionResult, RawTransaction, first_line

HEADER = "Data,Valor,Identificador,Descrição"
_AMOUNT = re.compile(r"^-?\d+\.\d{2}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class NubankAccountCsv(Parser):
    name = "nubank_conta_csv"
    banco = "nubank"
    product = "conta"
    METHODS = nu.METHODS
    NO_TOTALS = True  # o arquivo não tem saldo nem total

    @classmethod
    def detect(cls, path: Path) -> bool:
        return path.suffix.lower() == ".csv" and first_line(path) == HEADER

    def extract(self, path: Path) -> ExtractionResult:
        transactions = []
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            if next(reader) != HEADER.split(","):
                raise UnexpectedLayout(self.name, "cabecalho")
            for n, line in enumerate(reader, start=2):
                transactions.append(self._line(line, n))
        if not transactions:
            raise UnexpectedLayout(self.name, "arquivo_sem_lancamentos")
        return ExtractionResult(self.banco, self.product, transactions, segmentos=[])

    def _line(self, line: list[str], n: int) -> RawTransaction:
        # n = número da linha no arquivo, usado como "página" nas mensagens de erro
        if len(line) != 4:
            raise UnexpectedLayout(self.name, "numero_de_colunas", n)
        date_txt, amount_txt, ident, description = line
        try:
            data = datetime.strptime(date_txt, "%d/%m/%Y").date()
        except ValueError:
            raise UnexpectedLayout(self.name, "data", n) from None
        if not _AMOUNT.match(amount_txt):
            raise UnexpectedLayout(self.name, "valor", n)
        if not _UUID.match(ident):
            raise UnexpectedLayout(self.name, "identificador", n)
        valor = Decimal(amount_txt)

        tipo, rest = nu.split_type(description)  # no CSV o tipo vem separado do resto por " - "
        if tipo in nu.TYPES:
            if rest and not rest.startswith("- "):
                raise UnexpectedLayout(self.name, "separador_do_tipo", n)
            if (valor > 0) != (nu.TYPES[tipo].sign > 0):
                raise UnexpectedLayout(self.name, "sinal_incoerente_com_tipo", n)
            try:
                name, doc = nu.contraparte(tipo, rest)
            except nu.InvalidComplement as exc:
                raise UnexpectedLayout(self.name, str(exc), n) from None
        else:
            # tipo desconhecido: segue, e o mapa METHODS rejeita o arquivo depois (HistoricoDesconhecido)
            tipo, name, doc = description.split(" - ", 1)[0], "", ""
        return RawTransaction(data, tipo, valor, 0, name, doc, page=n)
```

## 5. Exemplo completo: PDF com saldo após cada lançamento (conta do Inter)

Layout (página 1): "Solicitado em: DD/MM/AAAA - HHhMM", nome do titular, linha "CPF/CNPJ: …,
Instituição: Banco Inter, Agência: …, Conta: …", período, resumo de saldos. Corpo: "D de Mês de
AAAA Saldo do dia: R$ X" e lançamentos `Tipo: "complemento" ±R$ valor R$ saldo_após`. O complemento
entre aspas pode continuar na linha seguinte. O rodapé é ignorado explicitamente.

Conferência: cada lançamento é um segmento (saldo anterior + valor == saldo após). O saldo de
abertura do primeiro não aparece, então ele é derivado do próprio lançamento. Checagens extras:
"Saldo do dia" == saldo do último lançamento do dia, e "Saldo total" do resumo == saldo final.

```python
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..models import PaymentMethod
from ..normalization import normalize_history, br_amount
from .base import UnexpectedLayout, Parser, ExtractionResult, Segment, RawTransaction, pdf_text

_MONTHS = {m: i for i, m in enumerate(
    "Janeiro Fevereiro Março Abril Maio Junho Julho Agosto Setembro Outubro Novembro Dezembro".split(), start=1)}
_V = r"-?R\$ -?\d{1,3}(?:\.\d{3})*,\d{2}"
_HDR = [  # linhas fixas do topo da página 1 (None = o nome do titular)
    re.compile(r"^\S+ em: \d{2}/\d{2}/\d{4} - \d{1,2}h\d{2}$"),
    None,
    re.compile(r"^CPF/CNPJ: .+, Instituição: Banco Inter, Agência: [\d-]+, Conta: [\d-]+$"),
    re.compile(r"^Período: \d{2}/\d{2}/\d{4} a \d{2}/\d{2}/\d{4}$"),
    re.compile(r"^Saldo total Saldo disponível: Saldo bloqueado:$"),
    re.compile(rf"^(?P<total>{_V}) (?P<disp>{_V}) (?P<bloq>{_V})$"),
    re.compile(r"^\(bloqueado \+ disponível\)$"),
]
_DAY = re.compile(rf"^(?P<d>\d{{1,2}}) de (?P<m>{'|'.join(_MONTHS)}) de (?P<a>\d{{4}}) "
                  rf"Saldo do dia: (?P<s>{_V})(?: Valor Saldo por transação)?$")
_TYPES: dict[str, tuple[PaymentMethod, int, bool]] = {  # tipo -> (meio, sinal, tem contraparte)
    "Pix enviado": (PaymentMethod.PIX, -1, True),
    "Pix recebido": (PaymentMethod.PIX, +1, True),
    "Pix enviado devolvido": (PaymentMethod.REFUND, +1, True),
    "Pix recebido devolvido": (PaymentMethod.REFUND, -1, True),
    "Resgate": (PaymentMethod.INVESTMENT, +1, False),
    "Aplicacao": (PaymentMethod.INVESTMENT, -1, False),
}
_ENTRY = re.compile(rf'^(?P<tipo>[^:"]+): (?P<q>".*?) (?P<v>{_V}) (?P<s>{_V})$')
_FOOTER = re.compile(r"^(?:Fale com a gente|SAC: .*Ouvidoria: .*)$")
_PIX_ISPB = re.compile(r"^Cp :\d{8}-(?P<nome>.+)$")
_PIX_BRANCH_ACCOUNT = re.compile(r"^\d{5} \d{8,9} (?P<nome>.+)$")
_INVESTMENT = re.compile(r"^CDB POS DI LIQ\. BANCO INTER S ?A$")


class InterAccountPdf(Parser):
    name = "inter_conta_pdf"
    banco = "inter"
    product = "conta"
    METHODS = {normalize_history(k): v[0] for k, v in _TYPES.items()}

    @classmethod
    def detect(cls, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        pages = pdf_text(path, 1)
        return bool(pages) and cls._header(pages[0].splitlines()) is not None

    @staticmethod
    def _header(lines: list[str]) -> re.Match[str] | None:
        if len(lines) <= len(_HDR) or not all(rx is None or rx.match(l) for rx, l in zip(_HDR, lines)):
            return None
        return _HDR[5].match(lines[5])

    def extract(self, path: Path) -> ExtractionResult:
        pages = pdf_text(path)
        first = pages[0].splitlines()
        summary = self._header(first)
        if summary is None:
            raise UnexpectedLayout(self.name, "cabecalho", 1)
        holder = first[1].strip()
        body = [(1, l) for l in first[len(_HDR):]]
        body += [(n, l) for n, p in enumerate(pages[1:], start=2) for l in p.splitlines()]

        transactions: list[RawTransaction] = []
        segmentos: list[Segment] = []
        day: date | None = None
        day_balance: Decimal | None = None
        balance: Decimal | None = None
        pending: list | None = None  # [página, data, tipo, aspas, valor] com aspas ainda abertas

        def check_day(num: int) -> None:
            if day_balance is not None and balance != day_balance:
                raise UnexpectedLayout(self.name, "saldo_do_dia_diferente_do_ultimo_lancamento", num)

        for num, line in body:
            if pending is not None:  # o complemento entre aspas continua nesta linha
                if not line.endswith('"') or '"' in line[:-1]:
                    raise UnexpectedLayout(self.name, "aspas_nao_fechadas", num)
                pending[3] += " " + line
                transactions.append(self._build(*pending, len(segmentos) - 1))
                pending = None
                continue
            if _FOOTER.match(line):
                continue
            if m := _DAY.match(line):
                check_day(num)
                day = date(int(m["a"]), _MONTHS[m["m"]], int(m["d"]))
                day_balance = br_amount(m["s"])
                continue
            if m := _ENTRY.match(line):
                if day is None:
                    raise UnexpectedLayout(self.name, "lancamento_sem_dia", num)
                valor, following = br_amount(m["v"]), br_amount(m["s"])
                segmentos.append(Segment(f"lançamento {len(segmentos)}",
                                         following - valor if balance is None else balance, following))
                balance = following
                item = [num, day, m["tipo"], m["q"], valor]
                if m["q"].count('"') == 1:
                    pending = item
                else:
                    transactions.append(self._build(*item, len(segmentos) - 1))
                continue
            raise UnexpectedLayout(self.name, "linha_desconhecida", num)
        if pending is not None:
            raise UnexpectedLayout(self.name, "aspas_nao_fechadas", len(pages))
        check_day(len(pages))
        if not transactions:
            raise UnexpectedLayout(self.name, "arquivo_sem_lancamentos")
        if br_amount(summary["total"]) != balance:
            raise UnexpectedLayout(self.name, "saldo_total_diferente_do_ultimo_lancamento", 1)
        return ExtractionResult(self.banco, self.product, transactions, segmentos, [holder])

    def _build(self, num, day, tipo, quotes, valor, segment) -> RawTransaction:
        if not (quotes.startswith('"') and quotes.endswith('"') and quotes.count('"') == 2):
            raise UnexpectedLayout(self.name, "complemento_sem_aspas", num)
        content = quotes[1:-1].strip()
        if tipo not in _TYPES:
            return RawTransaction(day, tipo, valor, segment, page=num)  # o mapa rejeita depois
        _, sign, has_counterparty = _TYPES[tipo]
        if (valor > 0) != (sign > 0):
            raise UnexpectedLayout(self.name, "sinal_incoerente_com_tipo", num)
        if not has_counterparty:
            if not _INVESTMENT.match(content):
                raise UnexpectedLayout(self.name, "produto_de_investimento", num)
            return RawTransaction(day, tipo, valor, segment, page=num)
        m = _PIX_ISPB.match(content) or _PIX_BRANCH_ACCOUNT.match(content)
        if not m:
            raise UnexpectedLayout(self.name, "complemento_pix", num)
        return RawTransaction(day, tipo, valor, segment, m["nome"].strip(), page=num)
```

## 6. Outros padrões de layout

- **Saldo do dia** (Bradesco conta): um `Segment` por dia, `opening` = saldo do dia anterior e
  `closing` = saldo declarado do dia. O extrato todo pode ser outro segmento (`segment=(dia, 0)`).
- **Fatura de cartão** (Nubank, Bradesco, Santander): um segmento por fatura com `opening = -saldo
  anterior` e `closing = -total`. Pagamento recebido e saldo anterior → `omitted=True`. Vários
  portadores → todos em `holder_names`. Compra internacional e IOF são lançamentos separados
  (`juros_iof`).
- **Várias faturas num PDF**: `Segment.document = "fatura AAAA-MM-DD"` e `REJECT_BY_DOCUMENT =
  True`. O rótulo do documento vai para o relatório, então use só tipo + data.
- **Cidade grudada no estabelecimento** (faturas): `cities.split_city(texto, truncated_width=13)`
  quando o campo de cidade tem largura fixa. Sem cidade reconhecida → `review_reason`.
- **Ano ausente nas datas da fatura** ("05/03"): deduza pelo vencimento da fatura, com teste para
  a virada de ano.
- **Lançamento repetido na emenda de extratos** (o mesmo dia no fim de um e no começo do outro):
  `duplicate=True`, para entrar na conferência do seu trecho sem ir para a saída.

## 7. Testes

Parser falso para testar o pipeline sem PDF (`extraction/tests/test_pipeline.py`):

```python
from datetime import date
from decimal import Decimal as D

from statement.models import PaymentMethod
from statement.parsers.base import Parser, ExtractionResult, Segment, RawTransaction


class ParserFake(Parser):
    """Lê um .fake inventado: 'saldo_inicial;saldo_final' e depois 'AAAA-MM-DD;historico;valor;nome;doc'."""

    name, banco, product = "fake_conta", "fakebank", "conta"
    METHODS = {"PIX ENVIADO": PaymentMethod.PIX, "PIX RECEBIDO": PaymentMethod.PIX,
               "COMPRA DEBITO": PaymentMethod.DEBIT_CARD, "TARIFA": PaymentMethod.FEE}

    @classmethod
    def detect(cls, path):
        return path.suffix == ".fake"

    def extract(self, path):
        lines = path.read_text("utf-8").splitlines()
        begin, end = (D(x) for x in lines[0].split(";"))
        txs = []
        for l in lines[1:]:
            d, h, v, n, doc = l.split(";")
            txs.append(RawTransaction(date.fromisoformat(d), h, D(v), 0, n, doc))
        return ExtractionResult(self.banco, self.product, txs, [Segment("arquivo", begin, end)],
                                holder_names=["Fulano de Tal Exemplo"])
```

Use com `run(pasta, "u09", saida, privado, parsers=[ParserFake], people=frozenset())` e confira o
relatório e as linhas exatas do CSV.

CSV real com linhas inventadas:

```python
HDR = "Data,Valor,Identificador,Descrição\n"
U1 = "11111111-2222-4333-8444-555555555555"


def _csv(tmp_path, lines):
    p = tmp_path / "extrato.csv"
    p.write_text(HDR + "".join(l + "\n" for l in lines), "utf-8")
    return p


@pytest.mark.parametrize("line,motivo", [
    (f"02/01/2024,12.50,{U1},Compra no débito - PADARIA MODELO", "sinal_incoerente_com_tipo"),
    (f"2024-01-02,-12.50,{U1},Compra no débito - PADARIA MODELO", "data"),
    (f"02/01/2024,-12.5,{U1},Compra no débito - PADARIA MODELO", "valor"),
])
def test_rejeita_fora_do_layout(tmp_path, line, motivo):
    with pytest.raises(UnexpectedLayout) as exc:
        NubankAccountCsv().extract(_csv(tmp_path, [line]))
    assert exc.value.motivo == motivo
```

PDF sem PDF de verdade: troque `pdf_text` do módulo do parser por páginas inventadas.

```python
from statement.parsers import inter_conta_pdf as inter
from statement.pipeline import run

PAGINA = "\n".join([
    "Solicitado em: 05/01/2024 - 8h20",
    "FULANO DE TESTE",
    "CPF/CNPJ: ***.123.456-**, Instituição: Banco Inter, Agência: 0001, Conta: 1234567-8",
    "Período: 01/01/2024 a 05/01/2024",
    "Saldo total Saldo disponível: Saldo bloqueado:",
    "R$ 90,00 R$ 90,00 R$ 0,00",
    "(bloqueado + disponível)",
    "2 de Janeiro de 2024 Saldo do dia: R$ 90,00",
    'Pix enviado: "Cp :12345678-PADARIA MODELO" -R$ 10,00 R$ 90,00',
])


def test_inter_ponta_a_ponta(tmp_path, monkeypatch):
    monkeypatch.setattr(inter, "pdf_text", lambda path, max_pages=None: (PAGINA,))
    arquivo = tmp_path / "raw" / "extrato.pdf"
    arquivo.parent.mkdir()
    arquivo.write_bytes(b"%PDF-1.4")  # o conteúdo não é lido: pdf_text foi trocado
    execucao = run(arquivo.parent, "u09", tmp_path / "u09.csv", tmp_path / "privado",
                   parsers=[inter.InterAccountPdf], people=frozenset())
    assert execucao.reports[0].status == "aceito" and execucao.reports[0].reconciliacao == "ok"
    assert (tmp_path / "u09.csv").read_text("utf-8").splitlines()[1:] == [
        "u09,2024-01-02,PIX ENVIADO,PADARIA MODELO,-10.00,saida,pix,inter",
    ]
```
