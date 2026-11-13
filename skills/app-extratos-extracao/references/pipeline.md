# Pipeline: modelo da linha, normalização, transformação e validação

Código do projeto de referência (`extraction/src/statement/`).

## Sumário

1. `models.py`: contrato da linha
2. `normalization.py`
3. `pipeline.py`: relatório, extração e transformação
4. `validation.py`: última barreira antes do disco
5. `cli.py`

## 1. `models.py`

```python
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .normalization import normalize_history, normalize_text

COLUMNS = ("id_usuario", "data", "historico", "contraparte", "valor", "tipo", "meio", "banco")
INDIVIDUAL_PERSON = "PESSOA_FISICA"


class TransactionType(StrEnum):
    INCOME = "entrada"
    EXPENSE = "saida"


class PaymentMethod(StrEnum):
    PIX = "pix"
    TED_DOC = "ted_doc"
    BANK_SLIP = "boleto"
    DEBIT_CARD = "cartao_debito"
    CREDIT_CARD = "cartao_credito"
    INVOICE_PAYMENT = "pagamento_fatura"
    FEE = "tarifa"
    INTEREST_IOF = "juros_iof"
    INVESTMENT = "investimento"
    YIELD = "rendimento"
    SALARY = "salario"
    WITHDRAWAL = "saque"
    REFUND = "estorno"
    INTERNAL_TRANSFER = "transferencia_interna"
    OTHER = "outros"


class OutputRow(BaseModel):
    """Uma linha do CSV final. Só é montada depois da anonimização."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id_usuario: str
    data: date
    historico: str
    contraparte: str
    valor: Decimal
    tipo: TransactionType
    meio: PaymentMethod
    banco: str

    @field_validator("id_usuario")
    @classmethod
    def _check_user(cls, v: str) -> str:
        if not re.fullmatch(r"u\d{2}", v):
            raise ValueError("id_usuario deve ser 'u' + 2 dígitos (ex.: u07)")
        return v

    @field_validator("banco")
    @classmethod
    def _check_bank(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError("banco deve ser slug minúsculo (ex.: bradesco)")
        return v

    @field_validator("historico")
    @classmethod
    def _check_history(cls, v: str) -> str:
        if not v:
            raise ValueError("historico vazio")
        if v != normalize_history(v):
            raise ValueError("historico fora da forma normalizada")
        return v

    @field_validator("contraparte")
    @classmethod
    def _check_counterparty(cls, v: str) -> str:
        if v != normalize_text(v):
            raise ValueError("contraparte fora da forma normalizada")
        return v

    @field_validator("valor")
    @classmethod
    def _amount(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("valor não finito")
        if v == 0:
            raise ValueError("valor zero não tem tipo definido")
        if v != v.quantize(Decimal("0.01")):
            raise ValueError("valor com mais de 2 casas decimais")
        return v.quantize(Decimal("0.01"))

    @model_validator(mode="after")
    def _check_sign_type(self) -> OutputRow:
        expected = TransactionType.INCOME if self.valor > 0 else TransactionType.EXPENSE
        if self.tipo != expected:
            raise ValueError("tipo incoerente com o sinal do valor")
        return self

    def as_csv_row(self) -> list[str]:
        return [self.id_usuario, self.data.isoformat(), self.historico, self.contraparte,
                f"{self.valor:.2f}", self.tipo.value, self.meio.value, self.banco]
```

`strict=True` impede conversões silenciosas (um `float` no lugar de `Decimal` é erro).

## 2. `normalization.py`

```python
import re
import unicodedata
from decimal import Decimal, InvalidOperation

_SPACES = re.compile(r"\s+")
_PUNCTUATION_ONLY = re.compile(r"^[^\w]+$")
_HAS_DIGIT = re.compile(r"\d")


def normalize_text(text: str) -> str:
    """Maiúsculas, Unicode NFC e espaços simples. Mantém acentos e pontuação."""
    text = unicodedata.normalize("NFC", text).upper()
    return _SPACES.sub(" ", text).strip()


def normalize_history(text: str) -> str:
    """Forma canônica do histórico: também tira tokens com dígito (nº de documento, parcela,
    código) e pontuação solta (o "-" de "TED - 123")."""
    tokens = [t for t in normalize_text(text).split(" ")
              if t and not _HAS_DIGIT.search(t) and not _PUNCTUATION_ONLY.match(t)]
    return " ".join(tokens)


def strip_accents(text: str) -> str:
    """Tira acentos (só para comparações internas; nunca para a saída)."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


_BR_AMOUNT = re.compile(r"^(?P<sinal_ini>[-+])?\s*(?:R\$)?\s*(?P<sinal_meio>[-+])?\s*"
                        r"(?P<num>\d{1,3}(?:\.\d{3})*|\d+),(?P<cent>\d{2})\s*(?P<sinal_fim>[-+])?$")


def br_amount(text: str) -> Decimal:
    """"1.234,56", "R$ 1.234,56", "-R$ 1,00", "R$ -1,00" e "1.234,56-" -> Decimal.

    Qualquer outra forma levanta ValueError: o parser trata os próprios sufixos (C/D) antes.
    """
    m = _BR_AMOUNT.match(text.strip())
    if not m:
        raise ValueError("valor em formato não reconhecido")
    signs = [s for s in (m["sinal_ini"], m["sinal_meio"], m["sinal_fim"]) if s]
    if len(signs) > 1:
        raise ValueError("valor com mais de um sinal")
    try:
        valor = Decimal(f"{m['num'].replace('.', '')}.{m['cent']}")
    except InvalidOperation as exc:
        raise ValueError("valor inválido") from exc
    return -valor if signs == ["-"] else valor
```

## 3. `pipeline.py`

Relatório por arquivo (só contagens e códigos):

```python
ACCEPTED, REJECTED = "aceito", "rejeitado"


@dataclass
class FileReport:
    arquivo: str
    parser: str = ""
    periodo_inicio: str = ""
    periodo_fim: str = ""
    linhas_extraidas: int = 0
    linhas_gravadas: int = 0
    linhas_revisar: int = 0
    linhas_duplicadas: int = 0
    linhas_omitidas: int = 0
    documentos_rejeitados: int = 0
    historicos_desconhecidos: int = 0
    segmentos: int = 0
    segmentos_divergentes: int = 0
    reconciliacao: str = "nao_executada"
    status: str = REJECTED
    motivo: str = ""


@dataclass
class Execution:
    reports: list[FileReport]
    lines: list[OutputRow] = field(default_factory=list)
    # texto ORIGINAL (sem anonimizar) de cada linha, na mesma ordem de `lines`:
    # {"historico", "contraparte"}. Nunca vai para o CSV nem para o treino; a API só o grava cifrado.
    originals: list[dict[str, str]] = field(default_factory=list)
    to_review: list[dict[str, str]] = field(default_factory=list)
    unknown: list[dict[str, str]] = field(default_factory=list)
    holder_names: list[str] = field(default_factory=list)
    leak: LeakDetected | None = None

    @property
    def exit_code(self) -> int:
        if self.leak is not None:
            return 2
        return 0 if all(r.status == ACCEPTED for r in self.reports) else 1
```

Fase 1, extrair e conferir cada arquivo:

```python
def _extract(path, label, parsers) -> _Extracted:
    item = _Extracted(path, FileReport(arquivo=label))
    rel = item.report
    try:
        parser = choose_parser(path, parsers)
        rel.parser = parser.name
        result = parser.extract(path)
    except UnexpectedLayout as exc:
        rel.motivo = f"{exc.code}:{exc.motivo}" + (f"@p{exc.page}" if exc.page else "")
        return item
    except ExtractionError as exc:
        rel.motivo = exc.code
        return item
    except Exception as exc:  # noqa: BLE001 - a mensagem pode ter conteúdo do extrato
        rel.motivo = f"erro_no_parser:{getattr(exc, 'code', type(exc).__name__)}"
        return item

    rel.linhas_extraidas = len(result.transactions)
    if result.transactions:
        dates = sorted(t.data for t in result.transactions)
        rel.periodo_inicio, rel.periodo_fim = dates[0].isoformat(), dates[-1].isoformat()
    if parser.NO_TOTALS:
        if result.segmentos:
            rel.motivo = "segmentos_em_formato_sem_totais"
            return item
        rel.reconciliacao = "sem_totais"
        item.parser, item.result = parser, result
        return item
    status = check(result)
    rel.segmentos, rel.segmentos_divergentes = status.segmentos, status.divergent
    rejected: list[str] = []
    try:
        if parser.REJECT_BY_DOCUMENT:
            result, rejected = split_divergent_documents(result)
        reconcile(result)
    except ExtractionError as exc:
        rel.reconciliacao, rel.motivo = "falhou", exc.code
        return item
    rel.reconciliacao = "ok"
    if rejected:  # rótulos dos documentos são só tipo + data: nada pessoal
        rel.reconciliacao = "ok_com_documentos_rejeitados"
        rel.documentos_rejeitados = len(rejected)
        rel.motivo = "documentos_rejeitados:" + ";".join(rejected)
    item.parser, item.result = parser, result
    return item
```

Fase 2, normalizar e anonimizar cada lançamento:

```python
def _transform(item, user, names, execution, people=frozenset()) -> None:
    rel, parser, result = item.report, item.parser, item.result
    lines, originals, to_review, unknown, invalid = [], [], [], set(), 0

    duplicate_rows = sum(t.duplicate for t in result.transactions)
    omitted_rows = sum(t.omitted and not t.duplicate for t in result.transactions)
    for t in result.transactions:
        if t.duplicate or t.omitted:
            continue
        # mesma forma das chaves do mapa; patterns.remove só apaga dado pessoal
        historico = normalize_history(patterns.remove(t.historico, names))
        try:
            meio = parser.method_for(historico)
        except UnknownHistory as exc:
            unknown.add(exc.historico)
            continue
        contraparte = (Review(t.review_reason) if t.review_reason
                       else resolve_counterparty(t.contraparte, t.counterparty_document, meio, names))
        if isinstance(contraparte, Review):
            to_review.append({"id_usuario": user, "arquivo": rel.arquivo, "data": t.data.isoformat(),
                              "historico": historico, "contraparte_original": t.contraparte,
                              "valor": f"{t.valor:.2f}", "motivo": contraparte.motivo})
            continue
        contraparte = merchants.standardize(contraparte, meio, people)
        try:
            lines.append(OutputRow(
                id_usuario=user, data=t.data, historico=historico, contraparte=contraparte,
                valor=t.valor, tipo=TransactionType.INCOME if t.valor > 0 else TransactionType.EXPENSE,
                meio=meio, banco=result.banco))
        except ValidationError:  # a mensagem do pydantic inclui o valor: não propagar
            invalid += 1
        else:
            originals.append({"historico": normalize_history(t.historico), "contraparte": t.contraparte})

    rel.historicos_desconhecidos = len(unknown)
    execution.unknown.extend({"id_usuario": user, "parser": parser.name, "historico": h}
                             for h in sorted(unknown))
    if unknown:
        rel.motivo = "HistoricoDesconhecido"
        return
    if invalid:
        rel.motivo = f"linhas_invalidas:{invalid}"
        return
    rel.linhas_gravadas, rel.linhas_revisar, rel.linhas_duplicadas = len(lines), len(to_review), duplicate_rows
    rel.linhas_omitidas = omitted_rows
    rel.status = ACCEPTED
    execution.lines.extend(lines)
    execution.originals.extend(originals)
    execution.to_review.extend(to_review)
```

Fase 3, juntar e gravar:

```python
def run(source, user, output, private_dir, parsers=None, people=None) -> Execution:
    """`people`: nomes marcados como pessoa. None = lê os mapas de `private_dir`."""
    if not re.fullmatch(r"u\d{2}", user):
        raise ValueError("--usuario deve ser 'u' + 2 dígitos (ex.: u07)")
    extracted = [_extract(p, p.relative_to(source).as_posix() if source.is_dir() else p.name, parsers)
                 for p in _files(source)]  # arquivos da pasta, sem ocultos, em ordem
    return _finalize(extracted, user, output, private_dir, people=people)


def _finalize(extracted, user, output, private_dir, other_holders=frozenset(), people=None) -> Execution:
    execution = Execution(reports=[e.report for e in extracted])
    holders = {n for e in extracted if e.result for n in e.result.holder_names}
    execution.holder_names = sorted(holders)
    holder_names = sorted(holders | set(other_holders))
    names = patterns.names_regex(holder_names)
    people = merchants.declared_people(private_dir) if people is None else people
    for item in extracted:
        if item.result is not None:
            _transform(item, user, names, execution, people)
    _write_private(private_dir / "revisar.csv", user, execution.to_review)
    _write_private(private_dir / "historicos_desconhecidos.csv", user, execution.unknown)
    if any(r.status == ACCEPTED for r in execution.reports):
        try:
            write_csv(execution.lines, output, holder_names)
        except LeakDetected as exc:
            execution.leak = exc
    _write_report(output.with_name(output.stem + ".relatorio.csv"), execution.reports)
    return execution
```

`_write_private` substitui só as linhas daquele usuário e mantém as dos outros. `run_all` faz a
fase 1 de todas as pastas primeiro, junta os titulares de todas, faz `_finalize` por usuário e
grava o CSV geral passando de novo pelo validador, com todos os nomes.

## 4. `validation.py`

```python
class LeakDetected(ExtractionError):
    code = "VazamentoDetectado"

    def __init__(self, counts: Counter[str]):
        summary = ", ".join(f"{tipo}={n}" for tipo, n in sorted(counts.items()))
        super().__init__(f"gravação bloqueada: possível dado pessoal no CSV ({summary})")
        self.counts = counts


def verify(lines, names) -> Counter[str]:
    """Conta, por tipo de padrão, quantas linhas têm algo proibido nos campos de texto."""
    counts: Counter[str] = Counter()
    for line in lines:
        found: set[str] = set()
        for value in (line.historico, line.contraparte):
            found.update(patterns.find(value, names))
        counts.update(found)
    return counts


def write_csv(lines, path, holder_names) -> None:
    """Valida tudo e só então grava (UTF-8 sem BOM, vírgula, '\\n'), num .tmp renomeado no fim."""
    counts = verify(lines, patterns.names_regex(list(holder_names)))
    if counts:
        raise LeakDetected(counts)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        with open(temp, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(COLUMNS)
            w.writerows(line.as_csv_row() for line in lines)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
```

## 5. `cli.py`

- `extrair --entrada <pasta|arquivo> --usuario uNN --saida <csv> [--privado data/privado]`
- `tudo [--raw data/raw] [--saida data/saida/transacoes.csv] [--privado data/privado]`. Cada
  subpasta numérica N vira o usuário `uNN`; uma pasta que não é número é erro, porque o pseudônimo
  não pode ser adivinhado.
- Os nomes das flags ficam em português; o código interno usa `dest=` em inglês
  (`add_argument("--entrada", dest="source", ...)`).
- Para cada arquivo imprime: status, parser, período, extraídas/gravadas/revisar/duplicadas/
  omitidas, reconciliação e motivo. No fim, onde estão `revisar.csv` e
  `historicos_desconhecidos.csv`.
- Retorna `execution.exit_code` (0, 1 ou 2) ou 3 para argumento inválido.
