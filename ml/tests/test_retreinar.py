"""Retreino com correções dos usuários (dados inventados)."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from extrato.modelos import COLUNAS, PESSOA_FISICA
from ml.retreinar import PESO_CORRECAO, monta_treino, retreina

_T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _linha(contraparte, categoria, meio="cartao_debito", historico="COMPRA", valor=-10.0, i=0):
    return dict(id_usuario="u01", data="2024-01-02", historico=historico, contraparte=contraparte,
                valor=valor - i, tipo="saida", meio=meio, banco="banco_teste", categoria=categoria)


def _base():
    """Lojas inventadas por categoria + PIX para pessoa, com repetições suficientes para o TF-IDF."""
    lojas = {"mercado": ["SUPERMERCADO FICTICIO", "MERCADINHO INVENTADO"],
             "transporte": ["POSTO INVENTADO", "AUTO POSTO IMAGINARIO"],
             "alimentacao_fora": ["PIZZARIA IMAGINARIA", "LANCHONETE FICTICIA"],
             "compras": ["LOJA DE ROUPAS X", "MAGAZINE INVENTADO", "UNIVERSIDADE FICTICIA DO SUL"]}
    linhas = [_linha(nome, cat, i=i) for cat, nomes in lojas.items() for nome in nomes for i in range(8)]
    linhas += [_linha(PESSOA_FISICA, "transferencia_pessoa", "pix", "PIX ENVIADO", i=i) for i in range(10)]
    return pd.DataFrame(linhas)


def _correcoes(*itens):
    linhas = [{**_linha(c, cat, meio, hist, valor=-4.7), "corrigida_em": _T0 + timedelta(minutes=n)}
              for n, (c, cat, meio, hist) in enumerate(itens)]
    return pd.DataFrame(linhas, columns=[*COLUNAS, "categoria", "corrigida_em"])


def test_correcao_substitui_o_rotulo_da_mesma_loja_e_pesa_mais():
    base = _base()
    corr = _correcoes(("UNIVERSIDADE FICTICIA DO SUL", "alimentacao_fora", "pix", "PIX ENVIADO"))
    treino, pesos = monta_treino(base, corr)
    da_loja = treino[treino["contraparte"] == "UNIVERSIDADE FICTICIA DO SUL"]
    assert set(da_loja["categoria"]) == {"alimentacao_fora"}  # as 8 do CSV base + a correção
    assert len(treino) == len(base) + 1 and pesos[-1] == PESO_CORRECAO and pesos[:-1].max() == 1


def test_correcao_em_pix_para_pessoa_nao_muda_os_outros_pix():
    corr = _correcoes((PESSOA_FISICA, "alimentacao_fora", "pix", "PIX ENVIADO"))
    treino, _ = monta_treino(_base(), corr)
    pix_base = treino.iloc[:-1][treino.iloc[:-1]["contraparte"] == PESSOA_FISICA]
    assert set(pix_base["categoria"]) == {"transferencia_pessoa"}


def test_correcoes_que_discordam_vale_a_mais_recente():
    corr = _correcoes(("MAGAZINE INVENTADO", "mercado", "cartao_debito", "COMPRA"),
                      ("MAGAZINE INVENTADO", "contas_servicos", "cartao_debito", "COMPRA"))
    treino, _ = monta_treino(_base(), corr)
    base_da_loja = treino.iloc[:-2][treino.iloc[:-2]["contraparte"] == "MAGAZINE INVENTADO"]
    assert set(base_da_loja["categoria"]) == {"contas_servicos"}


def test_o_modelo_novo_aprende_a_correcao():
    base = _base()
    corr = _correcoes(("UNIVERSIDADE FICTICIA DO SUL", "alimentacao_fora", "pix", "PIX ENVIADO"))
    antes = retreina(base, corr.iloc[0:0]).modelo  # modelo sem a correção
    r = retreina(base, corr, modelo_atual=antes)
    assert r.acerto_correcoes_antes == 0.0 and r.acerto_correcoes_depois == 100.0
    assert r.correcoes == 1 and r.linhas_treino == len(base) + 1 and r.acerto_base_depois > 90
    nova = corr[list(COLUNAS)].assign(valor=-9.0)  # outra compra na mesma loja
    assert r.modelo.predict(nova)[0] == "alimentacao_fora"


def test_sem_modelo_atual_nao_ha_antes_e_base_vazia_e_erro():
    r = retreina(_base(), _correcoes(("POSTO INVENTADO", "transporte", "cartao_debito", "COMPRA")))
    assert r.acerto_correcoes_antes is None
    with pytest.raises(ValueError, match="vazio"):
        retreina(_base().iloc[0:0], _correcoes())
