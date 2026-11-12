"""Importar extrato grava no banco (falso) do usuário logado, sem repetir transações."""

from fastapi.testclient import TestClient

from api.auth import usuario_atual
from api.main import app

from api.tests.fakes import OUTRO, USUARIO

CAB = "Data,Valor,Identificador,Descrição\n"


def _linha(data, valor, n, desc="Compra no débito - PADARIA MODELO"):
    return f"{data},{valor},11111111-2222-4333-8444-{n:012d},{desc}\n"


def _envia(conteudo: str, nome="extrato.csv"):
    return TestClient(app).post("/api/extratos", files={"arquivo": (nome, conteudo.encode())})


def test_importa_e_grava_no_usuario_logado(db):
    r = _envia(CAB + _linha("02/01/2024", "-12.50", 1) + _linha("03/01/2024", "-8.00", 2), "fatura jan.csv")
    assert r.status_code == 200
    g = r.json()["gravacao"]
    assert (g["gravadas"], g["repetidas"]) == (2, 0)
    [extrato] = db.lista_extratos(USUARIO.id)
    assert extrato["nome_arquivo"] == "fatura jan.csv"
    assert len(db.transacoes(USUARIO.id)) == 2 and db.transacoes(OUTRO.id) == []


def test_mesmo_arquivo_duas_vezes_da_409(db):
    csv = CAB + _linha("02/01/2024", "-12.50", 1)
    assert _envia(csv).status_code == 200
    r = _envia(csv)
    assert r.status_code == 409
    assert len(db.transacoes(USUARIO.id)) == 1


def test_extratos_sobrepostos_nao_duplicam_mas_compras_iguais_de_verdade_entram(db):
    # extrato A: duas compras iguais no mesmo dia (duas de verdade)
    a = CAB + _linha("02/01/2024", "-8.94", 1) + _linha("02/01/2024", "-8.94", 2)
    # extrato B se sobrepõe: as mesmas duas + uma terceira igual + uma nova
    b = (CAB + _linha("02/01/2024", "-8.94", 3) + _linha("02/01/2024", "-8.94", 4)
         + _linha("02/01/2024", "-8.94", 5) + _linha("05/01/2024", "-30.00", 6))
    assert _envia(a, "a.csv").json()["gravacao"]["gravadas"] == 2
    g = _envia(b, "b.csv").json()["gravacao"]
    assert (g["gravadas"], g["repetidas"]) == (2, 2)
    assert len(db.transacoes(USUARIO.id)) == 4


def test_extrato_rejeitado_nao_grava(db):
    r = _envia("a,b,c\n1,2,3\n", "planilha.csv")
    assert r.status_code == 200
    assert r.json()["gravacao"] is None
    assert db.lista_extratos(USUARIO.id) == []


def test_apaga_extrato_e_suas_transacoes(db, logado_como):
    eid = _envia(CAB + _linha("02/01/2024", "-12.50", 1)).json()["gravacao"]["extrato_id"]
    cliente = TestClient(app)
    logado_como(OUTRO)
    assert cliente.delete(f"/api/extratos/{eid}").status_code == 404  # não é dele
    logado_como(USUARIO)
    assert cliente.delete(f"/api/extratos/{eid}").status_code == 204
    assert db.transacoes(USUARIO.id) == [] and cliente.get("/api/extratos").json() == []


def test_excluir_extrato_nao_apaga_o_que_outro_extrato_tambem_trouxe(db):
    cliente = TestClient(app)
    a = CAB + _linha("02/01/2024", "-8.94", 1) + _linha("03/01/2024", "-20.00", 2)
    b = CAB + _linha("03/01/2024", "-20.00", 3) + _linha("05/01/2024", "-30.00", 4)  # repete o dia 3
    ea = _envia(a, "a.csv").json()["gravacao"]["extrato_id"]
    eb = _envia(b, "b.csv").json()["gravacao"]["extrato_id"]
    assert cliente.delete(f"/api/extratos/{ea}").status_code == 204
    # o dia 3 também estava no extrato b: continua na conta, agora como transação do b
    assert sorted(t["data"].day for t in db.transacoes(USUARIO.id)) == [3, 5]
    [restante] = cliente.get("/api/extratos").json()
    assert restante["id"] == eb and restante["linhas_gravadas"] == 2
    assert cliente.delete(f"/api/extratos/{eb}").status_code == 204
    assert db.transacoes(USUARIO.id) == []


def test_sem_login_da_401():
    app.dependency_overrides.pop(usuario_atual)
    cliente = TestClient(app)
    assert cliente.get("/api/extratos").status_code == 401
    assert cliente.get("/api/painel", headers={"Authorization": "Basic abc"}).status_code == 401
