"""Corrigir categoria, renomear conversa, perfil, excluir conta, mês do dashboard e limite de uso."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from agente.assistente import Resposta
from api.dependencias import modelo_do_assistente
from api.limite import Limite
from api.main import app
from api.rotas import assistente as rota_assistente
from api.tests.falsos import OUTRO, USUARIO

CAB = "Data,Valor,Identificador,Descrição\n"


def _importa(cliente, linhas):
    csv = CAB + "".join(f"{d},{v},11111111-2222-4333-8444-{n:012d},Compra no débito - PADARIA MODELO\n"
                        for n, (d, v) in enumerate(linhas, 1))
    r = cliente.post("/api/extratos", files={"arquivo": ("e.csv", csv.encode())})
    assert r.status_code == 200
    return r


def test_corrigir_categoria_vale_so_para_o_dono(db, logado_como):
    cliente = TestClient(app)
    _importa(cliente, [("02/01/2024", "-12.50")])
    [t] = cliente.get("/api/transacoes").json()

    assert cliente.patch(f"/api/transacoes/{t['id']}", json={"categoria": "lazer"}).status_code == 400
    assert cliente.patch(f"/api/transacoes/{t['id']}", json={"categoria": "mercado"}).status_code == 204
    assert cliente.get("/api/transacoes").json()[0]["categoria"] == "mercado"
    assert db.linhas[0]["origem_categoria"] == "usuario"

    assert cliente.patch(f"/api/transacoes/{t['id']}", json={"categoria": None}).status_code == 204
    assert db.linhas[0]["categoria"] is None and db.linhas[0]["origem_categoria"] is None

    logado_como(OUTRO)
    assert cliente.patch(f"/api/transacoes/{t['id']}", json={"categoria": "mercado"}).status_code == 404


def test_renomear_conversa(db, logado_como):
    cliente = TestClient(app)
    cid = db.cria_conversa(USUARIO.id, "antigo")
    assert cliente.patch(f"/api/conversas/{cid}", json={"titulo": "   "}).status_code == 400
    assert cliente.patch(f"/api/conversas/{cid}", json={"titulo": " Gastos de março "}).status_code == 204
    assert cliente.get("/api/conversas").json()[0]["titulo"] == "Gastos de março"
    logado_como(OUTRO)
    assert cliente.patch(f"/api/conversas/{cid}", json={"titulo": "x"}).status_code == 404


def test_mudar_nome_do_perfil(db):
    cliente = TestClient(app)
    r = cliente.patch("/api/perfil", json={"nome": " Maria "})
    assert r.status_code == 200 and r.json() == {"nome": "Maria", "email": USUARIO.email}
    assert db.usuarios[USUARIO.id]["nome"] == "Maria"
    assert cliente.patch("/api/perfil", json={"nome": "  "}).status_code == 400


def test_excluir_conta_apaga_tudo_do_usuario_e_nada_dos_outros(db, logado_como):
    cliente = TestClient(app)
    _importa(cliente, [("02/01/2024", "-12.50")])
    db.cria_conversa(USUARIO.id, "minha")
    logado_como(OUTRO)
    _importa(cliente, [("03/01/2024", "-1.00")])
    logado_como(USUARIO)

    assert cliente.delete("/api/conta").status_code == 204
    assert db.transacoes(USUARIO.id) == [] and db.lista_extratos(USUARIO.id) == []
    assert db.lista_conversas(USUARIO.id) == []
    assert len(db.transacoes(OUTRO.id)) == 1


def test_painel_de_um_mes_escolhido(db):
    cliente = TestClient(app)
    for dia, valor in ((date(2024, 1, 5), "-100.00"), (date(2024, 3, 5), "-30.00")):
        db.linhas.append({"usuario_id": USUARIO.id, "extrato_id": None, "data": dia, "historico": "X",
                          "contraparte": "LOJA", "valor": Decimal(valor), "tipo": "saida", "meio": "pix",
                          "banco": "b", "categoria": "compras", "origem_categoria": "regra"})
    padrao = cliente.get("/api/painel").json()
    assert padrao["mes_valor"] == "2024-03" and padrao["despesas"] == 30.0
    assert [m["valor"] for m in padrao["meses"]] == ["2024-03", "2024-01"]
    janeiro = cliente.get("/api/painel?mes=2024-01").json()
    assert janeiro["mes"] == "jan/24" and janeiro["despesas"] == 100.0
    assert janeiro["grafico"]["rotulos"][-1] == "jan/24"  # os 6 meses terminam no mês escolhido
    assert cliente.get("/api/painel?mes=2024-13").status_code == 400


def test_limite_de_perguntas_no_chat(monkeypatch):
    app.dependency_overrides[modelo_do_assistente] = lambda: object()
    monkeypatch.setattr(rota_assistente, "responde", lambda *a, **k: Resposta("ok", None))
    cliente = TestClient(app)
    respostas = [cliente.post("/api/chat", json={"mensagem": "oi"}).status_code for _ in range(11)]
    assert respostas[:10] == [200] * 10
    assert respostas[10] == 429


def test_limite_libera_depois_da_janela(monkeypatch):
    agora = [1000.0]
    monkeypatch.setattr("api.limite.time.monotonic", lambda: agora[0])
    limite = Limite(2, 60, "testes")
    limite.confere("u")
    limite.confere("u")
    try:
        limite.confere("u")
        raise AssertionError("deveria ter barrado")
    except Exception as e:
        assert getattr(e, "status_code", None) == 429
    limite.confere("outro")  # cada usuário tem a sua contagem
    agora[0] += 61
    limite.confere("u")
