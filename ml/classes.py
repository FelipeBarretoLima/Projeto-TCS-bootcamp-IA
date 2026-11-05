"""Classes do target e regras determinísticas (usadas na rotulagem e, depois, antes do modelo).

Classes (definidas com o usuário em 2026-11-04):
    mercado, alimentacao_fora, transporte, compras, contas_servicos,
    transferencia_pessoa  (PIX/TED para pessoa física e pagamento a pessoa física na maquininha),
    receitas, financeiro

Regras (não dependem do nome do estabelecimento): investimento/rendimento/tarifa/juros/saque/estorno/
fatura/transferência própria -> financeiro; salário e entradas -> receitas; boleto pago ->
contas_servicos; PIX/TED ou cartão para PESSOA_FISICA -> transferencia_pessoa.
O que sobra (compra em estabelecimento, PIX para empresa) depende do nome: mapa (rotulagem) ou modelo.
"""

from __future__ import annotations

from enum import StrEnum

from extrato.modelos import PESSOA_FISICA, Meio, Tipo


class Categoria(StrEnum):
    MERCADO = "mercado"
    ALIMENTACAO_FORA = "alimentacao_fora"
    TRANSPORTE = "transporte"
    COMPRAS = "compras"
    CONTAS_SERVICOS = "contas_servicos"
    TRANSFERENCIA_PESSOA = "transferencia_pessoa"
    RECEITAS = "receitas"
    FINANCEIRO = "financeiro"


_FINANCEIRO = {Meio.INVESTIMENTO, Meio.RENDIMENTO, Meio.TARIFA, Meio.JUROS_IOF, Meio.SAQUE, Meio.ESTORNO,
               Meio.PAGAMENTO_FATURA, Meio.TRANSFERENCIA_INTERNA}


def por_regra(meio: Meio, tipo: Tipo, historico: str, contraparte: str) -> Categoria | None:
    """Categoria que não depende do nome do estabelecimento (None = depende do nome)."""
    if meio in _FINANCEIRO:
        return Categoria.FINANCEIRO
    if meio is Meio.SALARIO:
        return Categoria.RECEITAS
    if meio is Meio.OUTROS:
        if tipo is Tipo.ENTRADA:
            return Categoria.RECEITAS
        return Categoria.CONTAS_SERVICOS if "RECARGA" in historico else Categoria.FINANCEIRO
    if tipo is Tipo.ENTRADA:
        # crédito do cartão colocado na conta (Nubank) é movimento financeiro, não receita
        return Categoria.FINANCEIRO if meio is Meio.CARTAO_CREDITO else Categoria.RECEITAS
    if meio is Meio.BOLETO:
        return Categoria.CONTAS_SERVICOS
    if contraparte == PESSOA_FISICA:
        return Categoria.TRANSFERENCIA_PESSOA
    if meio in (Meio.PIX, Meio.TED_DOC) and not contraparte:
        return Categoria.TRANSFERENCIA_PESSOA
    return None
