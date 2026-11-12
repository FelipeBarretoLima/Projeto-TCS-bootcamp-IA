"""Retreino automático: a cada 15 correções, o modelo é treinado de novo e trocado (dados inventados)."""

import joblib
import pytest
from fastapi.testclient import TestClient

from api import config
from api.main import app
from api.services import retraining
from ml.retrain import CORRECTIONS_TO_RETRAIN
from ml.tests.test_retrain import _base
from ml.train import build_model

CAB = "Data,Valor,Identificador,Descrição\n"
N = CORRECTIONS_TO_RETRAIN


@pytest.fixture
def com_csv_base(tmp_path, monkeypatch):
    """CSV base de treino e um .pkl atual (inventados) no lugar dos reais."""
    base = _base()
    caminho = tmp_path / "rotuladas.csv"
    base.to_csv(caminho, index=False)
    monkeypatch.setattr(config, "CAMINHO_TREINO_BASE", caminho)
    pkl = tmp_path / "modelo.pkl"
    joblib.dump(build_model().fit(base.drop(columns=["categoria"]), base["categoria"]), pkl)
    monkeypatch.setattr(config, "CAMINHO_MODELO", pkl)
    return pkl


def _importa_e_lista(n):
    linhas = "".join(f"{d:02d}/01/2024,-4.70,11111111-2222-4333-8444-{d:012d},Compra no débito - "
                     f"UNIVERSIDADE FICTICIA DO SUL\n" for d in range(1, n + 1))
    cliente = TestClient(app)
    assert cliente.post("/api/extratos", files={"arquivo": ("e.csv", (CAB + linhas).encode())}).status_code == 200
    return cliente, [t["id"] for t in cliente.get("/api/transacoes", params={"inicio": "2024-01-01"}).json()]


def _corrige(cliente, ids, categoria="alimentacao_fora"):
    for i in ids:
        assert cliente.patch(f"/api/transacoes/{i}", json={"categoria": categoria}).status_code == 204


def test_correcao_fica_gravada_antes_de_verificar_o_retreino(db):
    cliente, [i] = _importa_e_lista(1)
    _corrige(cliente, [i])
    assert db.confirmacoes == 1 and db.treinos_ == []  # 1 correção: ainda não retreina


def test_retreina_na_15a_correcao_e_troca_o_modelo(db, com_csv_base):
    cliente, ids = _importa_e_lista(N + 2)
    antes = com_csv_base.stat().st_mtime_ns
    _corrige(cliente, ids[: N - 1])
    assert db.treinos_ == []
    _corrige(cliente, ids[N - 1: N])  # a 15ª
    [t] = db.treinos_
    assert t["status"] == "ok" and t["correcoes"] == N
    assert t["acerto_correcoes_antes"] == 0.0 and t["acerto_correcoes_depois"] == 100.0
    assert com_csv_base.stat().st_mtime_ns != antes  # .pkl novo no lugar
    assert com_csv_base.with_name("modelo.anterior.pkl").exists()  # e o anterior guardado
    # o contador recomeça: mais 2 correções não disparam outro retreino
    _corrige(cliente, ids[N:])
    assert len(db.treinos_) == 1


def test_modelo_novo_classifica_a_proxima_importacao(db, com_csv_base):
    cliente, ids = _importa_e_lista(N)
    assert {t["categoria"] for t in cliente.get("/api/transacoes", params={"inicio": "2024-01-01"}).json()} == {"compras"}
    _corrige(cliente, ids)
    nova = f"{CAB}20/02/2024,-4.70,11111111-2222-4333-8444-999999999999,Compra no débito - UNIVERSIDADE FICTICIA DO SUL\n"
    [t] = cliente.post("/api/extratos", files={"arquivo": ("f.csv", nova.encode())}).json()["transacoes"]
    assert (t["categoria"], t["origem_categoria"]) == ("alimentacao_fora", "modelo")


def test_correcao_para_sem_categoria_nao_conta(db, com_csv_base):
    cliente, ids = _importa_e_lista(N)
    _corrige(cliente, ids, categoria=None)
    assert db.treinos_ == []


def test_sem_csv_base_registra_erro_e_a_correcao_continua_valendo(db):
    cliente, ids = _importa_e_lista(N)
    _corrige(cliente, ids)
    [t] = db.treinos_
    assert t["status"] == "erro" and t["mensagem"].startswith("FileNotFoundError")
    assert all(l["categoria"] == "alimentacao_fora" for l in db.linhas)


def test_falha_na_verificacao_nao_atrapalha_a_correcao(db, monkeypatch):
    cliente, [i] = _importa_e_lista(1)
    monkeypatch.setattr(db, "correcoes_desde_ultimo_treino", lambda: 1 / 0)
    _corrige(cliente, [i])
    assert db.linhas[0]["categoria"] == "alimentacao_fora"


def test_nao_roda_dois_retreinos_juntos(db, com_csv_base):
    db.inicia_treino()  # um "rodando"
    assert retraining.executa_retreino() is None


def test_treino_usa_so_campos_anonimizados(db, com_csv_base, monkeypatch):
    cliente, ids = _importa_e_lista(N)
    vistos = {}

    def espiona(base, correcoes, modelo_atual=None):
        vistos["colunas"] = set(correcoes.columns)
        raise ValueError("parar aqui")

    monkeypatch.setattr(retraining, "retrain", espiona)
    _corrige(cliente, ids)
    assert "original_cifrado" not in vistos["colunas"] and "contraparte_original" not in vistos["colunas"]


def test_depois_de_um_erro_nao_retreina_a_cada_correcao(db):
    # sem CSV base nos testes: o retreino da 15ª correção falha
    cliente, ids = _importa_e_lista(N + 3)
    _corrige(cliente, ids[:N])
    assert [t["status"] for t in db.treinos_] == ["erro"]
    # antes, cada correção seguinte a um erro disparava outro retreino (que falhava de novo)
    _corrige(cliente, ids[N:])
    assert len(db.treinos_) == 1


def test_inicio_do_retreino_e_atomico(db, com_csv_base):
    """Quem inicia o retreino é o banco (inicia_treino_se_livre), não um "confere e depois grava"."""
    assert db.inicia_treino_se_livre() is not None
    assert db.inicia_treino_se_livre() is None
    assert retraining.executa_retreino() is None


# --- correções numa tabela própria: sobrevivem à exclusão do extrato ---

def _apaga_o_extrato(cliente):
    [extrato] = cliente.get("/api/extratos").json()
    assert cliente.delete(f"/api/extratos/{extrato['id']}").status_code == 204


def test_correcao_sobrevive_a_exclusao_do_extrato_e_conta_no_retreino(db, com_csv_base):
    cliente, ids = _importa_e_lista(N - 1)
    _corrige(cliente, ids)
    _apaga_o_extrato(cliente)
    assert db.linhas == [] and len(db.correcoes_para_treino()) == N - 1
    # um extrato novo e 1 correção completam as 15: o retreino usa também as do extrato excluído
    nova = f"{CAB}20/02/2024,-4.70,11111111-2222-4333-8444-999999999999,Compra no débito - UNIVERSIDADE FICTICIA DO SUL\n"
    assert cliente.post("/api/extratos", files={"arquivo": ("f.csv", nova.encode())}).status_code == 200
    [t] = cliente.get("/api/transacoes", params={"inicio": "2024-01-01"}).json()
    _corrige(cliente, [t["id"]])
    [treino] = db.treinos_
    assert treino["status"] == "ok" and treino["correcoes"] == N


def test_reimportar_e_corrigir_de_novo_nao_duplica_a_correcao(db):
    cliente, [i] = _importa_e_lista(1)
    _corrige(cliente, [i])
    _apaga_o_extrato(cliente)
    cliente, [j] = _importa_e_lista(1)  # o mesmo arquivo de novo
    _corrige(cliente, [j], categoria="transporte")
    [c] = db.correcoes_para_treino()
    assert c["categoria"] == "transporte"


def test_voltar_para_sem_categoria_desfaz_a_correcao(db):
    cliente, [i] = _importa_e_lista(1)
    _corrige(cliente, [i])
    _corrige(cliente, [i], categoria=None)
    assert db.correcoes_para_treino() == []


def test_excluir_a_conta_apaga_as_correcoes(db):
    cliente, ids = _importa_e_lista(2)
    _corrige(cliente, ids)
    assert cliente.delete("/api/conta").status_code == 204
    assert db.correcoes_para_treino() == []
