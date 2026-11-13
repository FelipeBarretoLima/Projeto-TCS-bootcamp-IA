# Anonimização: padrões, regra da contraparte e estabelecimentos

Código do projeto de referência (`extraction/src/statement/`). As listas de palavras foram
ajustadas com extratos reais: ao mudar uma, acrescente um teste com um nome inventado que mostre o
caso.

## Sumário

1. `patterns.py`: padrões de dado pessoal e nome do titular
2. `anonymization.py`: regra da contraparte
3. `merchants.py`: nome-base e pessoa na maquininha
4. `cities.py`: cidade no fim do nome
5. Casos para testar

## 1. `patterns.py`

Todos os padrões rodam sobre texto já em maiúsculas. `X`, `*` e `•` são os caracteres de máscara
dos bancos. A ordem importa na remoção: padrões longos primeiro, para um curto não cortar um
pedaço de outro (um CNPJ dentro de uma linha de boleto).

```python
import re

from .normalization import normalize_text, strip_accents

_M = r"[\d*•X]"  # dígito ou máscara

PATTERNS: dict[str, re.Pattern[str]] = {
    "boleto": re.compile(r"\d(?:[\s.]?\d){43,47}"),  # linha digitável (47/48) ou código de barras (44)
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "chave_pix_aleatoria": re.compile(
        r"\b[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\b"),
    "cnpj": re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}\s?/?\s?\d{4}-?\d{2}\b"),  # a barra às vezes vira espaço
    # CPF completo ou mascarado (•••.123.456-••, ***.123.456-**)
    "cpf": re.compile(rf"(?<![\w*•]){_M}{{3}}\.\s?{_M}{{3}}\.\s?{_M}{{3}}\s?-\s?{_M}{{2}}(?![\w*•])"),
    "cartao": re.compile(
        r"(?<![\w*•])\d{4}(?:[\s.-]?[\d*•X]{4}){2}[\s.-]?\d{4}\b"   # 16 posições, inteiro ou mascarado
        r"|(?<![A-Z])(?:[*•X]{2,}[\s.-]*)+\d{4}\b"                 # **** 1234 / XXXX.1234
        r"|\b\d{4}[\s.-]*[*•X]{2,}(?![A-Z])"                       # 1234 ****
        r"|\bFINAL\s*:?\s*\d{4}\b"                                 # "FINAL 1234"
        r"|\bCART[ÃA]O\s*(?:N[º°O.]?\s*)?:?\s*\d{4}\b"),           # "CARTÃO 1234"
    "agencia_conta": re.compile(
        r"\bAG(?:[ÊE]NCIA|\.)?\s*:?\s*\d[\d-]*"
        r"|\b(?:CONTA|C/C|CC)\s*(?:CORRENTE\s*)?(?:N[º°O.]?\s*)?:?\s*\d[\d.-]*"),
    "telefone": re.compile(r"(?:\+?55\s?)?(?:\(\d{2}\)|\b\d{2})\s?9?\d{4}[\s-]?\d{4}\b"),
    "cep": re.compile(r"\b\d{5}-?\d{3}\b"),
    "endereco": re.compile(
        r"\b(?:RUA|R\.|AV\.?|AVENIDA|TRAVESSA|TV\.|ALAMEDA|AL\.|RODOVIA|ROD\.|ESTRADA|PRA[ÇC]A|LARGO)"
        r"\s+[^\d,;]{2,}?,?\s*(?:N[º°O.]?\s*)?\d+"),
    "codigo_numerico": re.compile(r"\d(?:[.\-/]?\d){5,}"),  # qualquer sequência de 6+ dígitos
}

_CONNECTIVES = {"DE", "DA", "DO", "DAS", "DOS", "E", "D"}


def name_variants(name: str) -> list[str]:
    """Formas de um nome que não podem aparecer na saída: o nome completo e cada par de tokens
    consecutivos (sem conectivos). "MARIA DA SILVA SOUZA" -> "MARIA DA SILVA SOUZA",
    "MARIA SILVA", "SILVA SOUZA". Tokens soltos não entram: um sobrenome sozinho aparece em nomes
    de empresa e bloquearia linhas legítimas."""
    base = strip_accents(normalize_text(name))
    tokens = [t for t in re.findall(r"[A-Z]+", base) if t not in _CONNECTIVES and len(t) > 1]
    variants = {base} if base else set()
    variants.update(f"{a} {b}" for a, b in zip(tokens, tokens[1:]))
    return sorted(variants, key=len, reverse=True)


def names_regex(names: list[str]) -> re.Pattern[str] | None:
    """Uma regex (sobre texto sem acento) para todas as variantes. Entre os tokens aceita
    espaços e conectivos ("MARIA SILVA" casa com "MARIA DA SILVA")."""
    variants: set[str] = set()
    for name in names:
        variants.update(name_variants(name))
    if not variants:
        return None
    parts = []
    for v in sorted(variants, key=len, reverse=True):
        tokens = [re.escape(t) for t in v.split(" ")]
        parts.append(r"(?:\s+(?:(?:DE|DA|DO|DAS|DOS|E)\s+)*)".join(tokens))
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b")


def _strip_accents_same_length(text: str) -> str:
    """strip_accents que preserva posições (NFC: 1 caractere -> 1 caractere)."""
    converted = "".join(strip_accents(c)[:1] or c for c in text)
    assert len(converted) == len(text)
    return converted


def find(text: str, names=None) -> list[str]:
    """Tipos de dado pessoal presentes no texto (só os nomes dos tipos, nunca o trecho)."""
    text = normalize_text(text)
    found = [tipo for tipo, rx in PATTERNS.items() if rx.search(text)]
    if names is not None and names.search(_strip_accents_same_length(text)):
        found.append("nome_titular")
    return found


def remove(text: str, names=None) -> str:
    """Apaga todo trecho que casa com algum padrão (e os nomes do titular)."""
    text = normalize_text(text)
    for rx in PATTERNS.values():
        text = rx.sub(" ", text)
    if names is not None:
        base = _strip_accents_same_length(text)
        for m in reversed(list(names.finditer(base))):  # do fim para o começo: posições não mudam
            text = text[: m.start()] + " " + text[m.end():]
    return text
```

## 2. `anonymization.py`

```python
import re
from dataclasses import dataclass
from enum import StrEnum

from . import patterns
from .merchants import looks_like_company_by_name
from .models import INDIVIDUAL_PERSON, PaymentMethod
from .normalization import normalize_text

_COMPANY = re.compile(r"\b(?:LTDA|EIRELI|CIA|S\.A\.?|S/A|SA)(?=\W|$)")
_MICROCOMPANY = re.compile(r"\b(?:ME|MEI|EPP)\.?$")
_CNPJ_ROOT_AT_START = re.compile(r"^\d{2}[.\s]?\d{3}[.\s]?\d{3}\b")  # "12.345.678 NOME"
_LONG_DIGITS = re.compile(r"\d{8,}")                               # "NOME 12345678900": MEI com CPF no nome
_DIGITS_ONLY = re.compile(r"\D")
# beneficiário de boleto também pode ser pessoa (decisão do usuário)
_TRANSFER_METHODS = {PaymentMethod.PIX, PaymentMethod.TED_DOC, PaymentMethod.INTERNAL_TRANSFER,
                     PaymentMethod.BANK_SLIP}
_CARD_METHODS = {PaymentMethod.DEBIT_CARD, PaymentMethod.CREDIT_CARD}


class PartyClass(StrEnum):
    INDIVIDUAL_PERSON = "pf"
    COMPANY = "pj"
    AMBIGUOUS = "ambiguo"


@dataclass(frozen=True)
class Review:
    """A transação sai da saída e vai para data/privado/revisar.csv."""
    motivo: str  # código curto, sem conteúdo do extrato


def _has_cpf(text): return bool(patterns.PATTERNS["cpf"].search(text)) or len(_DIGITS_ONLY.sub("", text)) == 11
def _has_cnpj(text): return bool(patterns.PATTERNS["cnpj"].search(text)) or len(_DIGITS_ONLY.sub("", text)) == 14


def classify(name: str, document: str, meio: PaymentMethod) -> PartyClass:
    name_n, doc_n = normalize_text(name), normalize_text(document)
    cpf = _has_cpf(doc_n) if doc_n else bool(patterns.PATTERNS["cpf"].search(name_n))
    cnpj = _has_cnpj(doc_n) if doc_n else bool(patterns.PATTERNS["cnpj"].search(name_n))
    company = bool(_COMPANY.search(name_n))
    mei_with_cpf = meio in _TRANSFER_METHODS and bool(_LONG_DIGITS.search(name_n))
    if (cpf and cnpj) or _MICROCOMPANY.search(name_n) or _CNPJ_ROOT_AT_START.match(name_n) or mei_with_cpf:
        return PartyClass.AMBIGUOUS
    if cpf:
        return PartyClass.AMBIGUOUS if company else PartyClass.INDIVIDUAL_PERSON
    if cnpj or company:
        return PartyClass.COMPANY
    if meio in _TRANSFER_METHODS:
        return PartyClass.COMPANY if looks_like_company_by_name(name_n) else PartyClass.INDIVIDUAL_PERSON
    return PartyClass.COMPANY  # cartão sem documento: estabelecimento


# intermediários de maquininha/pagamento: o que vem depois do nome deles é o vendedor
_INTERMEDIARY = re.compile(r"^(JIM\.COM|INFINITEPAY|PAGSEGURO|MERCADOPAGO|SUMUP|PAG|PG|MP|TON|STONE|"
                           r"SAFRAPAY|GETNET|CIELO|PICPAY)\b")


def merchant(name: str) -> str:
    """Só o que vem antes do primeiro '*' ("IFOOD *RESTAURANTE X" -> "IFOOD"); intermediários
    conhecidos ficam só com o próprio nome, mesmo sem '*'."""
    name = name.split("*", 1)[0]
    m = _INTERMEDIARY.match(normalize_text(name))
    return m.group(1) if m else name


def _tidy(text: str) -> str:
    """Tira sobras de pontuação da remoção."""
    text = re.sub(r"\(\s*\)|\[\s*\]", " ", text)
    text = re.sub(r"(?:\s*[-–/|:,;]\s*){2,}", " - ", text)
    return normalize_text(text).strip(" -–/|:,;.")


def anonymize_text(text: str, names) -> str:
    return _tidy(patterns.remove(text, names))


def resolve_counterparty(name: str, document: str, meio: PaymentMethod, names) -> str | Review:
    """Valor final da coluna contraparte, ou Review se não dá para decidir com segurança."""
    if not normalize_text(name) and not normalize_text(document):
        return ""
    party_class = classify(name, document, meio)
    if party_class is PartyClass.INDIVIDUAL_PERSON:
        return INDIVIDUAL_PERSON
    if party_class is PartyClass.AMBIGUOUS:
        return Review("contraparte_ambigua")
    if not normalize_text(name):
        return ""  # empresa identificada só pelo CNPJ: não há nome para mostrar
    if names is not None and "nome_titular" in patterns.find(name, names):
        return Review("titular_no_nome_da_empresa")
    if meio in _CARD_METHODS:
        name = merchant(name)
    clean = anonymize_text(name, names)
    if not clean or not re.search(r"[^\W\d_]", clean):
        return Review("empresa_sem_nome_apos_limpeza")
    return clean
```

## 3. `merchants.py`

Roda depois da anonimização, só em compras com cartão e estornos, e é idêntica no treino e na
inferência: o modelo vê sempre o mesmo tipo de contraparte.

```python
import csv
import re
from functools import lru_cache
from importlib.resources import files

from .models import INDIVIDUAL_PERSON, PaymentMethod
from .normalization import normalize_text, strip_accents

MAP_FILES = ("estabelecimentos_revisar.csv", "estabelecimentos_novos.csv")  # mapas do usuário (data/privado)
METHODS_WITH_MERCHANT = {PaymentMethod.DEBIT_CARD, PaymentMethod.CREDIT_CARD, PaymentMethod.REFUND}


def base_name(contraparte: str) -> str:
    """Sem o número da loja no fim ("LOJA X 37", "LOJA X LJ09" -> "LOJA X"). A cidade não é
    cortada aqui: muitos nomes de loja terminam numa palavra que também é município."""
    return normalize_text(re.sub(r"\s+(LJ ?\d+|LOJA ?\d+|\d+)$", "", normalize_text(contraparte)))


@lru_cache(maxsize=1)
def _first_names() -> frozenset[str]:
    text = files("statement").joinpath("dados/primeiros_nomes.txt").read_text("utf-8")
    # palavras que são nome de pessoa e também palavra comum em nome de loja
    common = {"SANTA", "SANTO", "SAO", "BELA", "BOM", "BOA", "VIDA", "SOL", "LUZ", "PAZ", "ROSA", "FLOR",
              "DOCE", "CASA", "PRAIA", "MAR", "ESTRELA", "PRATA", "OURO", "CRISTAL", "AMERICA", "BRASIL",
              "PARIS", "NOVA", "REAL", "REI", "RAINHA", "PRINCESA", "ANJO", "FE", "GLORIA", "VITORIA",
              "AURORA", "SERENA", "LIS"}
    return frozenset(l for l in text.splitlines() if l and not l.startswith("#")) - common


_COMPANY_WORD = re.compile(r"\b(LTDA|SA|S/A|EIRELI|ME|EPP|MEI|CIA|COM|IND|MINI|BAR|BARES|CAR|PET|PAG|PG|MP|"
                           r"IFD|DM|NET|ACAI|DOCE|DOCES|BOLO|BOLOS|MODA|MODAS|AUTO|MOTO)\b")
_COMPANY_STEM = re.compile(
    r"COMERC|INDUSTR|SERVIC|SUPER|MERCAD|LOJA|POSTO|FARMA|DROGA|RESTAUR|BEER|CHOPP|LANCH|PIZZ|BURG|FOOD|CAFE|"
    r"PADARIA|PANIF|ACOUGUE|DISTRIB|BEBIDA|CONVENIENC|PECAS|ESTACION|VETERIN|STUDIO|ESTUDIO|SALAO|BELEZA|"
    r"CABELEIR|BARBEAR|BARBER|OTICA|CALCAD|CONFEC|PAPELAR|LIVRAR|ACADEMIA|CLINICA|ODONTO|SAUDE|HOTEL|POUSADA|"
    r"TURISMO|VIAGE|TRANSPORT|EXPRESS|DELIVERY|ESPETO|CHURRAS|SORVET|CONFEIT|PASTEL|EMPORIO|ARMAZEM|HORTI|FRUT|"
    r"QUITANDA|ATACAD|VAREJO|CENTER|SHOP|STORE|IFOOD|UBER|SHPP|TELECOM|ENERGIA|GAS\b|AGUA|ESPORT|SPORT|GAMES|"
    r"TECNOLOG|INFORMAT|CELULAR|ELETRO|MATERIA|CONSTRU|FERRAG|TINTAS|MADEIR|VIDRA|ESTOFAD|COLCHO|MOVEIS|"
    r"PRESENTE|UTILIDADE|VARIEDADE|ARTIGO|IMPORT|EXPORT|GRAFIC|COPIA|XEROX|CHAVEIRO|LAVANDER|LAVA|AUTOPEC|"
    r"MECANIC|BORRACH|PNEU|COMBUST|PEDAGIO|PARK|ESCOLA|CURSO|IGREJA|ASSOC|CLUBE|BANCO|SEGURO|CREDITO|PAGAMENT|"
    r"COMPANHIA|BRASILEIR|NACIONAL|VESTUAR|BRICOL|EMPREEND|PARTICIPAC|HOLDING|GRUPO|ADMINISTR|CONSULT|"
    r"ASSESSOR|ENGENH|INSTITUT|FUNDAC|COOPERAT|SINDICAT|SOLUC|SISTEMAS|"
    r"UNIVERSIDADE|FACULDADE|COLEGIO|ESTADUAL|MUNICIPAL|FEDERAL|PREFEITURA|SECRETARIA|GOVERNO|HOSPITAL")


def looks_like_company_by_name(name: str) -> bool:
    """PIX/TED sem CNPJ nem LTDA: é empresa? Nunca, se começa com um primeiro nome. É empresa
    quando tem palavra de empresa ou é uma palavra só ("CHEERS": em PIX, pessoa vem com nome e
    sobrenome). "JOAO SILVA LANCHES" (MEI com o nome do dono) continua pessoa."""
    c = strip_accents(name).upper()
    tokens = c.split()
    if not tokens:
        return False
    if re.sub(r"[^A-Z]", "", tokens[0]) in _first_names():
        return False
    if _COMPANY_WORD.search(c) or _COMPANY_STEM.search(c):
        return True
    return len(tokens) == 1 and len(re.sub(r"[^A-Z]", "", c)) >= 3


def looks_like_person(name: str) -> bool:
    c = strip_accents(name).upper()
    if re.search(r"\d", c) or _COMPANY_WORD.search(c) or _COMPANY_STEM.search(c) or not re.fullmatch(r"[A-Z ]+", c):
        return False
    names, toks = _first_names(), c.split()
    if 2 <= len(toks) <= 5:
        return len(toks[0]) >= 3 and toks[0] in names
    if len(toks) == 1 and len(c) >= 9:  # nome grudado: começa com primeiro nome e sobra um sobrenome
        return any(c.startswith(n) and len(c) - len(n) >= 4 for n in names if len(n) >= 4)
    return False


def declared_people(private_dir) -> frozenset[str]:
    """Nomes-base que o usuário marcou como pessoa (e_pessoa = sim) nos mapas privados."""
    people: set[str] = set()
    for arquivo in MAP_FILES:
        path = private_dir / arquivo
        if not path.exists():
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("e_pessoa") or "").strip().lower().startswith("sim"):
                    people.add(base_name(r["contraparte"]))
    return frozenset(people)


def standardize(contraparte: str, meio: PaymentMethod, people=frozenset()) -> str:
    """Contraparte final de um lançamento (só muda compras em estabelecimento)."""
    if meio not in METHODS_WITH_MERCHANT or contraparte in ("", INDIVIDUAL_PERSON):
        return contraparte
    base = base_name(contraparte)
    if not base:
        return contraparte
    return INDIVIDUAL_PERSON if base in people or looks_like_person(base) else base
```

`dados/primeiros_nomes.txt` é uma lista pública de primeiros nomes brasileiros, um por linha, em
maiúsculas e sem acento (linhas com `#` são comentários). Monte-a a partir de uma fonte pública
(ex.: nomes mais frequentes do Censo do IBGE).

## 4. `cities.py`

Faturas e extratos de cartão mostram "ESTABELECIMENTO CIDADE" sem posição fixa. A cidade é
reconhecida por dicionário (lista oficial de municípios do IBGE em `dados/municipios.txt`, sem
acento, maiúsculas), não por heurística. Pega o sufixo mais longo de até 6 tokens que é um
município. Com `truncated_width` (quando a bandeira corta o campo da cidade numa largura fixa),
também aceita o município cortado naquela largura. Sempre sobra ao menos um token para o
estabelecimento.

```python
def split_city(text: str, truncated_width: int | None = None) -> tuple[str, str] | None:
    tokens = text.split()
    for k in range(min(6, len(tokens) - 1), 0, -1):
        candidate = key(" ".join(tokens[-k:]))   # sem acento, maiúsculas, só A-Z0-9 e espaço
        exact = candidate in municipalities()
        truncated = truncated_width is not None and candidate in _truncated(truncated_width)
        if exact or truncated:
            return " ".join(tokens[:-k]), candidate
    return None
```

## 5. Casos para testar (com nomes inventados)

| Entrada | Esperado |
|---|---|
| PIX, nome "CICLANO DE TESTE", documento `•••.456.789-••` | `PESSOA_FISICA` |
| PIX, "PADARIA MODELO", sem documento | `PADARIA MODELO` (palavra de empresa) |
| PIX, "MARIA EXEMPLO", sem documento | `PESSOA_FISICA` (começa com primeiro nome) |
| PIX, "CHEERS", sem documento | `CHEERS` (uma palavra só: em PIX, pessoa vem com nome e sobrenome) |
| PIX, "LOJA EXEMPLO ME" | revisão `contraparte_ambigua` |
| PIX, "12.345.678 FULANO" | revisão `contraparte_ambigua` (raiz de CNPJ no começo = MEI) |
| cartão, "IFOOD *RESTAURANTE FICTICIO" | `IFOOD` |
| cartão, "PAG*FULANO" | `PAG` |
| cartão, "PADARIA MODELO 37" | `PADARIA MODELO` (nome-base) |
| cartão, "JOAO EXEMPLO" | `PESSOA_FISICA` (parece pessoa: primeiro nome + sobrenome, sem palavra de empresa) |
| cartão, "FULANO DE TAL" | `FULANO DE TAL` ("FULANO" não está na lista de primeiros nomes: escolha nomes de teste que estejam nela) |
| cartão, "FULANO EXEMPLO LANCHES" com o titular "Fulano Exemplo" | revisão `titular_no_nome_da_empresa` |
| histórico "TED 123456 FULANO DE TAL EXEMPLO" com o titular "Fulano de Tal Exemplo" | o nome e o número somem do histórico |
| linha com "AG 1234 CONTA 56789-0" que escapou | o validador bloqueia a gravação |
