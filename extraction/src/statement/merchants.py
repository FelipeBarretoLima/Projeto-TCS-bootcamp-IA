"""Merchant name standardization (part of the parser, identical in training and inference).

For card purchases (and their refunds), after anonymization:
  1. base name: removes the store number at the end ("LOJA X 37" -> "LOJA X");
  2. individual -> PESSOA_FISICA when
       - the base name looks like a person (starts with a Brazilian first name and has no
         company/business word; errs on purpose towards "is a person": user decision on 2026-11-04), or
       - the user marked e_pessoa = sim in the merchant map (data/privado, outside git).
This way the ML model sees at inference exactly the same kind of counterparty it saw in training.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from .models import INDIVIDUAL_PERSON, PaymentMethod
from .normalization import normalize_text, strip_accents

# merchant maps maintained by the user (read here only for the e_pessoa column)
MAP_FILES = ("estabelecimentos_revisar.csv", "estabelecimentos_novos.csv")
METHODS_WITH_MERCHANT = {PaymentMethod.DEBIT_CARD, PaymentMethod.CREDIT_CARD, PaymentMethod.REFUND}


def base_name(contraparte: str) -> str:
    """Merchant name without the store number at the end ("LOJA X 37", "LOJA X LJ09" -> "LOJA X").

    The city is not cut here: many store names end in a word that is also a municipality
    ("PADARIA MODELO", "LOJA AMERICANA"). Cutting the city is only safe where the layout
    guarantees the city at the end (Sicoob, done in the parser itself).
    """
    return normalize_text(re.sub(r"\s+(LJ ?\d+|LOJA ?\d+|\d+)$", "", normalize_text(contraparte)))


@lru_cache(maxsize=1)
def _first_names() -> frozenset[str]:
    text = files("statement").joinpath("dados/primeiros_nomes.txt").read_text("utf-8")
    common = {"SANTA", "SANTO", "SAO", "BELA", "BOM", "BOA", "VIDA", "SOL", "LUZ", "PAZ", "ROSA", "FLOR", "DOCE",
              "CASA", "PRAIA", "MAR", "ESTRELA", "PRATA", "OURO", "CRISTAL", "AMERICA", "BRASIL", "PARIS", "NOVA",
              "REAL", "REI", "RAINHA", "PRINCESA", "ANJO", "FE", "GLORIA", "VITORIA", "AURORA", "SERENA", "LIS"}
    return frozenset(l for l in text.splitlines() if l and not l.startswith("#")) - common


_COMPANY_WORD = re.compile(r"\b(LTDA|SA|S/A|EIRELI|ME|EPP|MEI|CIA|COM|IND|MINI|BAR|BARES|CAR|PET|PAG|PG|MP|IFD|"
                              r"DM|NET|ACAI|DOCE|DOCES|BOLO|BOLOS|MODA|MODAS|AUTO|MOTO)\b")
_COMPANY_STEM = re.compile(
    r"COMERC|INDUSTR|SERVIC|SUPER|MERCAD|LOJA|POSTO|FARMA|DROGA|RESTAUR|BEER|CHOPP|LANCH|PIZZ|BURG|FOOD|CAFE|"
    r"PADARIA|PANIF|ACOUGUE|DISTRIB|BEBIDA|CONVENIENC|PECAS|ESTACION|VETERIN|STUDIO|ESTUDIO|SALAO|BELEZA|"
    r"CABELEIR|BARBEAR|BARBER|OTICA|CALCAD|CONFEC|PAPELAR|LIVRAR|ACADEMIA|CLINICA|ODONTO|SAUDE|HOTEL|POUSADA|"
    r"TURISMO|VIAGE|TRANSPORT|EXPRESS|DELIVERY|ESPETO|CHURRAS|SORVET|CONFEIT|PASTEL|EMPORIO|ARMAZEM|HORTI|FRUT|"
    r"QUITANDA|ATACAD|VAREJO|CENTER|SHOP|STORE|IFOOD|UBER|SHPP|TELECOM|ENERGIA|GAS\b|AGUA|ESPORT|SPORT|GAMES|"
    r"TECNOLOG|INFORMAT|CELULAR|ELETRO|MATERIA|CONSTRU|FERRAG|TINTAS|MADEIR|VIDRA|ESTOFAD|COLCHO|MOVEIS|"
    r"PRESENTE|UTILIDADE|VARIEDADE|ARTIGO|IMPORT|EXPORT|GRAFIC|COPIA|XEROX|CHAVEIRO|LAVANDER|LAVA|AUTOPEC|"
    r"MECANIC|BORRACH|PNEU|COMBUST|PEDAGIO|PARK|ESCOLA|CURSO|IGREJA|ASSOC|CLUBE|BANCO|SEGURO|CREDITO|PAGAMENT|"
    # company legal name without LTDA/CNPJ (seen in Inter PIX): "... COMPANHIA BRASILEIRA DE ...", "COMERCIO DE VESTUARIO"
    r"COMPANHIA|BRASILEIR|NACIONAL|VESTUAR|BRICOL|EMPREEND|PARTICIPAC|HOLDING|GRUPO|ADMINISTR|CONSULT|"
    r"ASSESSOR|ENGENH|INSTITUT|FUNDAC|COOPERAT|SINDICAT|SOLUC|SISTEMAS|"
    # public bodies and institutions ("UNIVERSIDADE ESTADUAL DE LONDRINA")
    r"UNIVERSIDADE|FACULDADE|COLEGIO|ESTADUAL|MUNICIPAL|FEDERAL|PREFEITURA|SECRETARIA|GOVERNO|HOSPITAL")


def looks_like_company_by_name(name: str) -> bool:
    """For PIX/TED without CNPJ or LTDA: is the name a company? Never, if it starts with a first name.

    Company when it does NOT start with a person's first name and
      - has a company/business word: "BAR E RESTAURANTE VALENTINO", "UNIVERSIDADE ESTADUAL DE
        LONDRINA", "LEROY MERLIN COMPANHIA BRASILEIRA DE BRICOLAGEM"; or
      - is a single word: "CHEERS" (in PIX, a person always comes with first and last name).
    "JOAO SILVA LANCHES" (MEI with the owner's name) and "MARIA" remain a person.
    """
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
    if len(toks) == 1 and len(c) >= 9:  # glued name: starts with a first name and a surname is left over
        return any(c.startswith(n) and len(c) - len(n) >= 4 for n in names if len(n) >= 4)
    return False


def declared_people(private_dir: Path) -> frozenset[str]:
    """Base names marked by the user as a person (e_pessoa = sim / sim (auto)) in the maps."""
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


def standardize(contraparte: str, meio: PaymentMethod, people: frozenset[str] = frozenset()) -> str:
    """Final counterparty of an entry (only changes merchant purchases)."""
    if meio not in METHODS_WITH_MERCHANT or contraparte in ("", INDIVIDUAL_PERSON):
        return contraparte
    base = base_name(contraparte)
    if not base:
        return contraparte
    return INDIVIDUAL_PERSON if base in people or looks_like_person(base) else base
