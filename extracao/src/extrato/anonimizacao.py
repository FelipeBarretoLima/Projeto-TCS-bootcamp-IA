"""Anonimização dos campos de texto de uma transação.

Regras de contraparte (determinísticas, na ordem):
  1. CPF e CNPJ juntos, sufixo de microempresa (ME, MEI, EPP), nome começando pela
     raiz de CNPJ (padrões de MEI) ou, só em PIX/TED/transferência/boleto, nome com
     8+ dígitos seguidos (MEI com CPF no nome)                      -> ambíguo (revisar)
     (no cartão, número no nome é código da loja: "LOJA.COM 12345678 X" é empresa)
  2. CPF (completo ou mascarado)                                    -> PESSOA_FISICA,
     exceto se o nome tiver marcador de empresa                     -> ambíguo
  3. CNPJ ou marcador de empresa (LTDA, S.A., S/A, EIRELI, CIA)     -> empresa
  4. Sem documento nem marcador, em PIX/TED/transferência/boleto   -> PESSOA_FISICA
     (na dúvida, o token fixo nunca vaza nada), exceto se o nome não começar com primeiro nome de
     pessoa e tiver palavra de empresa ou for uma palavra só -> empresa
     (`estabelecimentos.parece_empresa_pelo_nome`; ex.: "BAR E RESTAURANTE X", "CHEERS",
     "UNIVERSIDADE ESTADUAL DE LONDRINA")
  5. Sem documento nem marcador, nos demais meios (cartão…)        -> empresa
O nome de empresa passa por `padroes.remove` (documentos, contas, nomes do titular…).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from . import padroes
from .estabelecimentos import parece_empresa_pelo_nome
from .modelos import PESSOA_FISICA, Meio
from .normalizacao import normaliza_texto

_EMPRESA = re.compile(r"\b(?:LTDA|EIRELI|CIA|S\.A\.?|S/A|SA)(?=\W|$)")
_MICROEMPRESA = re.compile(r"\b(?:ME|MEI|EPP)\.?$")
_RAIZ_CNPJ_NO_INICIO = re.compile(r"^\d{2}[.\s]?\d{3}[.\s]?\d{3}\b")  # "12.345.678 NOME" / "12 345 678 NOME"
_DIGITOS_LONGOS = re.compile(r"\d{8,}")  # "NOME 12345678900": MEI com CPF no nome
_SO_DIGITOS = re.compile(r"\D")
# beneficiário de boleto também pode ser pessoa (decisão do usuário, 2026-11-04)
_MEIOS_DE_TRANSFERENCIA = {Meio.PIX, Meio.TED_DOC, Meio.TRANSFERENCIA_INTERNA, Meio.BOLETO}
_MEIOS_DE_CARTAO = {Meio.CARTAO_DEBITO, Meio.CARTAO_CREDITO}


class Classe(StrEnum):
    PESSOA_FISICA = "pf"
    EMPRESA = "pj"
    AMBIGUO = "ambiguo"


@dataclass(frozen=True)
class Revisar:
    """A transação sai do CSV e vai para data/privado/revisar.csv."""

    motivo: str  # código curto, sem conteúdo do extrato


def _tem_cpf(texto: str) -> bool:
    return bool(padroes.PADROES["cpf"].search(texto)) or len(_SO_DIGITOS.sub("", texto)) == 11


def _tem_cnpj(texto: str) -> bool:
    return bool(padroes.PADROES["cnpj"].search(texto)) or len(_SO_DIGITOS.sub("", texto)) == 14


def classifica(nome: str, documento: str, meio: Meio) -> Classe:
    nome_n, doc_n = normaliza_texto(nome), normaliza_texto(documento)
    cpf = _tem_cpf(doc_n) if doc_n else bool(padroes.PADROES["cpf"].search(nome_n))
    cnpj = _tem_cnpj(doc_n) if doc_n else bool(padroes.PADROES["cnpj"].search(nome_n))
    empresa = bool(_EMPRESA.search(nome_n))

    mei_com_cpf = meio in _MEIOS_DE_TRANSFERENCIA and bool(_DIGITOS_LONGOS.search(nome_n))
    if (cpf and cnpj) or _MICROEMPRESA.search(nome_n) or _RAIZ_CNPJ_NO_INICIO.match(nome_n) or mei_com_cpf:
        return Classe.AMBIGUO
    if cpf:
        return Classe.AMBIGUO if empresa else Classe.PESSOA_FISICA
    if cnpj or empresa:
        return Classe.EMPRESA
    if meio in _MEIOS_DE_TRANSFERENCIA:
        return Classe.EMPRESA if parece_empresa_pelo_nome(nome_n) else Classe.PESSOA_FISICA
    return Classe.EMPRESA


# intermediários de maquininha/pagamento: o que vem depois do nome deles é o vendedor (muitas vezes
# um autônomo, ou seja, uma pessoa). Alguns bancos não usam '*' (ex.: "JIM.COM 12345678 VENDEDOR").
_INTERMEDIARIO = re.compile(r"^(JIM\.COM|INFINITEPAY|PAGSEGURO|MERCADOPAGO|SUMUP|PAG|PG|MP|TON|STONE|SAFRAPAY|"
                            r"GETNET|CIELO|PICPAY)\b")


def estabelecimento(nome: str) -> str:
    """Nome de estabelecimento de cartão: só o que vem antes do primeiro '*'.

    "IFOOD *RESTAURANTE X" -> "IFOOD"; "PAG*FULANO" -> "PAG". O que vem depois do '*'
    é o sub-lojista (às vezes uma pessoa) e só aumenta a cardinalidade. Intermediários conhecidos
    ficam só com o próprio nome mesmo sem '*': "JIM.COM 12345678 FULANO" -> "JIM.COM".
    A cidade não é tratada aqui: cada parser já entrega o nome sem ela.
    """
    nome = nome.split("*", 1)[0]
    m = _INTERMEDIARIO.match(normaliza_texto(nome))
    return m.group(1) if m else nome


def _arruma(texto: str) -> str:
    """Tira os restos de pontuação deixados pela remoção."""
    texto = re.sub(r"\(\s*\)|\[\s*\]", " ", texto)
    texto = re.sub(r"(?:\s*[-–/|:,;]\s*){2,}", " - ", texto)
    return normaliza_texto(texto).strip(" -–/|:,;.")


def anonimiza_texto(texto: str, nomes: re.Pattern[str] | None) -> str:
    """Remove dados pessoais de um texto livre (histórico ou nome de empresa)."""
    return _arruma(padroes.remove(texto, nomes))


def resolve_contraparte(
    nome: str, documento: str, meio: Meio, nomes: re.Pattern[str] | None
) -> str | Revisar:
    """Valor final da coluna contraparte, ou Revisar se não dá para decidir com segurança."""
    if not normaliza_texto(nome) and not normaliza_texto(documento):
        return ""
    classe = classifica(nome, documento, meio)
    if classe is Classe.PESSOA_FISICA:
        return PESSOA_FISICA
    if classe is Classe.AMBIGUO:
        return Revisar("contraparte_ambigua")
    if not normaliza_texto(nome):
        return ""  # empresa identificada só pelo CNPJ: sem nome para mostrar
    if nomes is not None and "nome_titular" in padroes.encontra(nome, nomes):
        return Revisar("titular_no_nome_da_empresa")
    if meio in _MEIOS_DE_CARTAO:
        nome = estabelecimento(nome)
    limpo = anonimiza_texto(nome, nomes)
    if not limpo or not re.search(r"[^\W\d_]", limpo):
        return Revisar("empresa_sem_nome_apos_limpeza")
    return limpo
