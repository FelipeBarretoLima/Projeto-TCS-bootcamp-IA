"""GET /api/transacoes: transações salvas do usuário logado, com filtro de período e categoria."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.transactions import inicio_da_janela
from api.tests.fakes import OUTRO, USUARIO


def _t(dia, categoria, valor="-10.00", mes=1):
    return {"data": date(2024, mes, dia), "historico": "COMPRA", "contraparte": "LOJA", "valor": Decimal(valor),
            "tipo": "saida", "meio": "cartao_debito", "banco": "nubank", "categoria": categoria,
            "origem_categoria": "regra" if categoria else None}


@pytest.fixture
def com_transacoes(db):
    db.grava_extrato(USUARIO.id, nome_arquivo="jan.csv", hash_arquivo="a", parser="nubank_csv",
                     periodo_inicio=None, periodo_fim=None,
                     transacoes=[_t(5, "mercado", "-50.00"), _t(10, "transporte", "-20.00"),
                                 _t(20, None, "-5.00"), _t(3, "mercado", "-30.00", mes=2)])
    db.grava_extrato(OUTRO.id, nome_arquivo="outro.csv", hash_arquivo="b", parser="nubank_csv",
                     periodo_inicio=None, periodo_fim=None, transacoes=[_t(7, "mercado", "-99.00")])
    return db


def _busca(**params):
    return TestClient(app).get("/api/transacoes", params=params)


def test_sem_filtro_devolve_todas_do_usuario_da_mais_recente(com_transacoes):
    r = _busca()
    assert r.status_code == 200
    assert [t["data"] for t in r.json()] == ["2024-02-03", "2024-01-20", "2024-01-10", "2024-01-05"]
    assert "-99.00" not in [t["valor"] for t in r.json()]  # nada do outro usuário


def test_nao_diz_de_onde_veio_a_categoria(com_transacoes):
    assert all("origem_categoria" not in t for t in _busca().json())


def test_filtra_por_periodo_inclusivo(com_transacoes):
    r = _busca(inicio="2024-01-05", fim="2024-01-10")
    assert [t["data"] for t in r.json()] == ["2024-01-10", "2024-01-05"]


def test_filtra_so_pela_data_inicial(com_transacoes):
    assert [t["data"] for t in _busca(inicio="2024-02-01").json()] == ["2024-02-03"]


def test_filtra_por_categoria(com_transacoes):
    r = _busca(categoria="mercado")
    assert [t["valor"] for t in r.json()] == ["-30.00", "-50.00"]


def test_filtra_sem_categoria(com_transacoes):
    r = _busca(categoria="sem_categoria")
    assert [(t["data"], t["categoria"]) for t in r.json()] == [("2024-01-20", None)]


def test_combina_periodo_e_categoria(com_transacoes):
    r = _busca(inicio="2024-01-01", fim="2024-01-31", categoria="mercado")
    assert [t["data"] for t in r.json()] == ["2024-01-05"]


def test_sem_extratos_devolve_lista_vazia():
    assert _busca().json() == []


def test_categoria_invalida_da_400(com_transacoes):
    assert _busca(categoria="lazer").status_code == 400


def test_periodo_invertido_da_400(com_transacoes):
    assert _busca(inicio="2024-02-01", fim="2024-01-01").status_code == 400


def test_data_mal_formatada_da_422(com_transacoes):
    assert _busca(inicio="05/01/2024").status_code == 422


# --- período e filtro padrão (últimos 6 meses, terminando no mês da última transação) ---

@pytest.mark.parametrize("ultima, esperado", [
    (date(2024, 3, 15), date(2023, 10, 1)),   # vira o ano
    (date(2024, 6, 30), date(2024, 1, 1)),
    (date(2024, 12, 1), date(2024, 7, 1)),
    (date(2024, 1, 31), date(2023, 8, 1)),
])
def test_inicio_da_janela_de_6_meses(ultima, esperado):
    assert inicio_da_janela(ultima) == esperado


def test_periodo_sem_transacoes():
    r = TestClient(app).get("/api/transacoes/periodo")
    assert r.status_code == 200
    assert r.json() == {"primeira": None, "ultima": None, "padrao_inicio": None, "padrao_fim": None}


def test_periodo_padrao_sao_os_6_meses_ate_a_ultima_transacao(db):
    db.grava_extrato(USUARIO.id, nome_arquivo="a.csv", hash_arquivo="a", parser="p", periodo_inicio=None,
                     periodo_fim=None, transacoes=[_t(10, None, mes=1), _t(20, None, mes=12)])
    assert TestClient(app).get("/api/transacoes/periodo").json() == {
        "primeira": "2024-01-10", "ultima": "2024-12-20",
        "padrao_inicio": "2024-07-01", "padrao_fim": "2024-12-20"}


def test_periodo_curto_comeca_na_primeira_transacao(com_transacoes):
    # transações só de jan e fev/2024: a janela iria até set/2023, mas a primeira transação é de 05/01
    assert TestClient(app).get("/api/transacoes/periodo").json() == {
        "primeira": "2024-01-05", "ultima": "2024-02-03",
        "padrao_inicio": "2024-01-05", "padrao_fim": "2024-02-03"}


@pytest.mark.parametrize("transacao_id", [0, -1, 2**63])
def test_id_fora_do_intervalo_do_banco_responde_422_e_nao_500(transacao_id):
    r = TestClient(app).patch(f"/api/transacoes/{transacao_id}", json={"categoria": "mercado"})
    assert r.status_code == 422
