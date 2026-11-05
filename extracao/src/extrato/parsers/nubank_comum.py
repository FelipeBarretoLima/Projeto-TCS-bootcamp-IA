"""Vocabulário da conta Nubank, comum ao CSV exportado e ao extrato em PDF.

Só entram tipos de lançamento já vistos nos extratos. Tipo novo = HistoricoDesconhecido.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..modelos import Meio
from ..normalizacao import normaliza_historico

Regra = Literal["transferencia", "estabelecimento", "beneficiario", "estorno", "nenhuma"]


@dataclass(frozen=True)
class TipoNubank:
    meio: Meio
    sinal: int  # -1 sempre saída, +1 sempre entrada
    contraparte: Regra


# texto exatamente como a Nubank escreve (maiúsculas/minúsculas importam)
TIPOS: dict[str, TipoNubank] = {
    "Transferência enviada pelo Pix": TipoNubank(Meio.PIX, -1, "transferencia"),
    "Transferência recebida pelo Pix": TipoNubank(Meio.PIX, +1, "transferencia"),
    "Transferência Recebida": TipoNubank(Meio.TED_DOC, +1, "transferencia"),
    "Reembolso recebido pelo Pix": TipoNubank(Meio.ESTORNO, +1, "transferencia"),
    "Compra no débito via NuPay": TipoNubank(Meio.CARTAO_DEBITO, -1, "estabelecimento"),
    "Compra no débito": TipoNubank(Meio.CARTAO_DEBITO, -1, "estabelecimento"),
    "Pagamento de boleto efetuado": TipoNubank(Meio.BOLETO, -1, "beneficiario"),
    "Depósito Recebido por Boleto": TipoNubank(Meio.BOLETO, +1, "nenhuma"),
    "Pagamento de fatura": TipoNubank(Meio.PAGAMENTO_FATURA, -1, "nenhuma"),
    "Aplicação RDB": TipoNubank(Meio.INVESTIMENTO, -1, "nenhuma"),
    "Resgate RDB": TipoNubank(Meio.INVESTIMENTO, +1, "nenhuma"),
    "Valor adicionado na conta por cartão de crédito": TipoNubank(Meio.CARTAO_CREDITO, +1, "nenhuma"),
    "Recarga de celular": TipoNubank(Meio.OUTROS, -1, "nenhuma"),
    "Crédito em conta": TipoNubank(Meio.OUTROS, +1, "nenhuma"),
    "Estorno": TipoNubank(Meio.ESTORNO, +1, "estorno"),
}

MEIOS: dict[str, Meio] = {normaliza_historico(k): t.meio for k, t in TIPOS.items()}

# do mais longo para o mais curto: "Compra no débito via NuPay" antes de "Compra no débito"
_ORDEM = sorted(TIPOS, key=len, reverse=True)

# documento como a Nubank mostra; no PDF pode vir quebrado por espaço/linha
_DOC = (r"(?P<doc>•••\.\s*\d{3}\.\s*\d{3}\s*-\s*••"
        r"|\d{2}\.\s*\d{3}\.\s*\d{3}\s*/\s*\d{4}\s*-\s*\d{2})")
_TRANSFERENCIA = re.compile(r"^(?:-\s+)?(?P<nome>.+?)\s+-\s+" + _DOC + r"(?:\s+-\s+.*)?$")
# variante sem documento nem banco, vista no PDF: "NOME" ou "NOME (Transferência enviada)".
# Sem dígito e sem " - ": se houvesse documento/banco, cairia no formato completo acima.
_TRANSFERENCIA_SO_NOME = re.compile(r"^(?P<nome>(?:(?! - )[^()\d])+?)(?: \(Transferência enviada\))?$")

# o complemento fixo do "Valor adicionado…" se intercala com a quebra de linha do tipo no PDF
_VALOR_ADICIONADO_PDF = re.compile(
    r"^Valor adicionado na conta por (?:cartão )?Valor adicionado para Pix no Crédito (?:cartão )?de crédito$"
)


def desfaz_intercalacao(texto: str) -> str:
    if _VALOR_ADICIONADO_PDF.match(texto):
        return "Valor adicionado na conta por cartão de crédito - Valor adicionado para Pix no Crédito"
    return texto


def separa_tipo(descricao: str) -> tuple[str, str]:
    """('Compra no débito', 'LOJA X') ou (descricao, '') se o tipo não for conhecido."""
    for tipo in _ORDEM:
        if descricao == tipo:
            return tipo, ""
        if descricao.startswith(tipo + " "):
            return tipo, descricao[len(tipo):].strip()
    return descricao, ""


class ComplementoInvalido(ValueError):
    """O complemento não segue o formato esperado para o tipo (mensagem sem conteúdo)."""


def contraparte(tipo: str, complemento: str) -> tuple[str, str]:
    """(nome, documento) da contraparte, conforme a regra do tipo."""
    regra = TIPOS[tipo].contraparte if tipo in TIPOS else "nenhuma"
    resto = re.sub(r"^-\s+", "", complemento).strip()
    if regra == "nenhuma":
        return "", ""
    if regra == "transferencia":
        m = _TRANSFERENCIA.match(complemento)
        if m:
            return m["nome"].strip(), re.sub(r"\s+", "", m["doc"])
        m = _TRANSFERENCIA_SO_NOME.match(resto)
        if m and tipo == "Transferência enviada pelo Pix":
            return m["nome"].strip(), ""
        raise ComplementoInvalido("transferencia_sem_documento")
    if regra == "estorno":
        # "Estorno - Compra no débito - LOJA": o estabelecimento é o último trecho
        sub_tipo, sub_resto = separa_tipo(resto)
        if sub_tipo in TIPOS:
            resto = re.sub(r"^-\s+", "", sub_resto).strip()
    if not resto:
        raise ComplementoInvalido(f"{regra}_vazio")
    return resto, ""
