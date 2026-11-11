"""Padronização do nome de estabelecimento (parte do parser, igual no treino e na aplicação).

Para compras no cartão (e estornos delas), depois da anonimização:
  1. nome-base: tira o número de loja do fim ("LOJA X 37" -> "LOJA X");
  2. pessoa física -> PESSOA_FISICA quando
       - o nome-base parece de pessoa (começa com primeiro nome brasileiro e não tem palavra de
         empresa/ramo; erra de propósito para o lado de "é pessoa": decisão do usuário em 2026-11-04), ou
       - o usuário marcou e_pessoa = sim no mapa de estabelecimentos (data/privado, fora do git).
Assim o modelo de ML vê na aplicação exatamente o mesmo tipo de contraparte que viu no treino.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from .modelos import PESSOA_FISICA, Meio
from .normalizacao import normaliza_texto, sem_acento

# mapas de estabelecimentos mantidos pelo usuário (lidos aqui só pela coluna e_pessoa)
ARQUIVOS_MAPA = ("estabelecimentos_revisar.csv", "estabelecimentos_novos.csv")
MEIOS_COM_ESTABELECIMENTO = {Meio.CARTAO_DEBITO, Meio.CARTAO_CREDITO, Meio.ESTORNO}


def nome_base(contraparte: str) -> str:
    """Nome do estabelecimento sem o número de loja no fim ("LOJA X 37", "LOJA X LJ09" -> "LOJA X").

    A cidade não é cortada aqui: muitos nomes de loja terminam em palavra que também é município
    ("PADARIA MODELO", "LOJA AMERICANA"). O corte de cidade só é seguro onde o layout garante a
    cidade no fim (Sicoob, feito no próprio parser).
    """
    return normaliza_texto(re.sub(r"\s+(LJ ?\d+|LOJA ?\d+|\d+)$", "", normaliza_texto(contraparte)))


@lru_cache(maxsize=1)
def _primeiros_nomes() -> frozenset[str]:
    texto = files("extrato").joinpath("dados/primeiros_nomes.txt").read_text("utf-8")
    comuns = {"SANTA", "SANTO", "SAO", "BELA", "BOM", "BOA", "VIDA", "SOL", "LUZ", "PAZ", "ROSA", "FLOR", "DOCE",
              "CASA", "PRAIA", "MAR", "ESTRELA", "PRATA", "OURO", "CRISTAL", "AMERICA", "BRASIL", "PARIS", "NOVA",
              "REAL", "REI", "RAINHA", "PRINCESA", "ANJO", "FE", "GLORIA", "VITORIA", "AURORA", "SERENA", "LIS"}
    return frozenset(l for l in texto.splitlines() if l and not l.startswith("#")) - comuns


_EMPRESA_PALAVRA = re.compile(r"\b(LTDA|SA|S/A|EIRELI|ME|EPP|MEI|CIA|COM|IND|MINI|BAR|BARES|CAR|PET|PAG|PG|MP|IFD|"
                              r"DM|NET|ACAI|DOCE|DOCES|BOLO|BOLOS|MODA|MODAS|AUTO|MOTO)\b")
_EMPRESA_RADICAL = re.compile(
    r"COMERC|INDUSTR|SERVIC|SUPER|MERCAD|LOJA|POSTO|FARMA|DROGA|RESTAUR|BEER|CHOPP|LANCH|PIZZ|BURG|FOOD|CAFE|"
    r"PADARIA|PANIF|ACOUGUE|DISTRIB|BEBIDA|CONVENIENC|PECAS|ESTACION|VETERIN|STUDIO|ESTUDIO|SALAO|BELEZA|"
    r"CABELEIR|BARBEAR|BARBER|OTICA|CALCAD|CONFEC|PAPELAR|LIVRAR|ACADEMIA|CLINICA|ODONTO|SAUDE|HOTEL|POUSADA|"
    r"TURISMO|VIAGE|TRANSPORT|EXPRESS|DELIVERY|ESPETO|CHURRAS|SORVET|CONFEIT|PASTEL|EMPORIO|ARMAZEM|HORTI|FRUT|"
    r"QUITANDA|ATACAD|VAREJO|CENTER|SHOP|STORE|IFOOD|UBER|SHPP|TELECOM|ENERGIA|GAS\b|AGUA|ESPORT|SPORT|GAMES|"
    r"TECNOLOG|INFORMAT|CELULAR|ELETRO|MATERIA|CONSTRU|FERRAG|TINTAS|MADEIR|VIDRA|ESTOFAD|COLCHO|MOVEIS|"
    r"PRESENTE|UTILIDADE|VARIEDADE|ARTIGO|IMPORT|EXPORT|GRAFIC|COPIA|XEROX|CHAVEIRO|LAVANDER|LAVA|AUTOPEC|"
    r"MECANIC|BORRACH|PNEU|COMBUST|PEDAGIO|PARK|ESCOLA|CURSO|IGREJA|ASSOC|CLUBE|BANCO|SEGURO|CREDITO|PAGAMENT|"
    # razão social sem LTDA/CNPJ (vista em PIX do Inter): "... COMPANHIA BRASILEIRA DE ...", "COMERCIO DE VESTUARIO"
    r"COMPANHIA|BRASILEIR|NACIONAL|VESTUAR|BRICOL|EMPREEND|PARTICIPAC|HOLDING|GRUPO|ADMINISTR|CONSULT|"
    r"ASSESSOR|ENGENH|INSTITUT|FUNDAC|COOPERAT|SINDICAT|SOLUC|SISTEMAS|"
    # órgãos e instituições ("UNIVERSIDADE ESTADUAL DE LONDRINA")
    r"UNIVERSIDADE|FACULDADE|COLEGIO|ESTADUAL|MUNICIPAL|FEDERAL|PREFEITURA|SECRETARIA|GOVERNO|HOSPITAL")


def parece_empresa_pelo_nome(nome: str) -> bool:
    """Para PIX/TED sem CNPJ nem LTDA: o nome é de empresa? Nunca, se começar com primeiro nome.

    Empresa quando NÃO começa com primeiro nome de pessoa e
      - tem palavra de empresa/ramo: "BAR E RESTAURANTE VALENTINO", "UNIVERSIDADE ESTADUAL DE
        LONDRINA", "LEROY MERLIN COMPANHIA BRASILEIRA DE BRICOLAGEM"; ou
      - é uma palavra só: "CHEERS" (no PIX, pessoa vem sempre com nome e sobrenome).
    "JOAO SILVA LANCHES" (MEI com o nome do dono) e "MARIA" continuam pessoa.
    """
    c = sem_acento(nome).upper()
    tokens = c.split()
    if not tokens:
        return False
    if re.sub(r"[^A-Z]", "", tokens[0]) in _primeiros_nomes():
        return False
    if _EMPRESA_PALAVRA.search(c) or _EMPRESA_RADICAL.search(c):
        return True
    return len(tokens) == 1 and len(re.sub(r"[^A-Z]", "", c)) >= 3


def parece_pessoa(nome: str) -> bool:
    c = sem_acento(nome).upper()
    if re.search(r"\d", c) or _EMPRESA_PALAVRA.search(c) or _EMPRESA_RADICAL.search(c) or not re.fullmatch(r"[A-Z ]+", c):
        return False
    nomes, toks = _primeiros_nomes(), c.split()
    if 2 <= len(toks) <= 5:
        return len(toks[0]) >= 3 and toks[0] in nomes
    if len(toks) == 1 and len(c) >= 9:  # nome colado: começa com um primeiro nome e sobra um sobrenome
        return any(c.startswith(n) and len(c) - len(n) >= 4 for n in nomes if len(n) >= 4)
    return False


def pessoas_declaradas(dir_privado: Path) -> frozenset[str]:
    """Nomes-base marcados pelo usuário como pessoa (e_pessoa = sim / sim (auto)) nos mapas."""
    pessoas: set[str] = set()
    for arquivo in ARQUIVOS_MAPA:
        caminho = dir_privado / arquivo
        if not caminho.exists():
            continue
        with open(caminho, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("e_pessoa") or "").strip().lower().startswith("sim"):
                    pessoas.add(nome_base(r["contraparte"]))
    return frozenset(pessoas)


def padroniza(contraparte: str, meio: Meio, pessoas: frozenset[str] = frozenset()) -> str:
    """Contraparte final de um lançamento (só muda compras em estabelecimento)."""
    if meio not in MEIOS_COM_ESTABELECIMENTO or contraparte in ("", PESSOA_FISICA):
        return contraparte
    base = nome_base(contraparte)
    if not base:
        return contraparte
    return PESSOA_FISICA if base in pessoas or parece_pessoa(base) else base
