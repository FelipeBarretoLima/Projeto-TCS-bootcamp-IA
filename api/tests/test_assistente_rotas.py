"""Dashboard e chat. O Gemini é trocado por uma resposta fixa (nenhuma chamada externa)."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from agente.assistente import Resposta
from api.dependencias import modelo_do_assistente
from api.main import app
from api.rotas import assistente as rota

from api.tests.falsos import OUTRO, USUARIO

GRAFICO = {"tipo": "barras", "titulo": "Teste", "rotulos": ["jan/24"],
           "series": [{"nome": "Gastos", "valores": [10.0]}], "formato": "moeda"}


@pytest.fixture
def chamadas(monkeypatch):
    feitas = []

    def responde_falso(modelo, df, pergunta, historico=()):
        feitas.append({"pergunta": pergunta, "historico": list(historico), "linhas": len(df)})
        return Resposta(f"resposta para: {pergunta}", GRAFICO)

    app.dependency_overrides[modelo_do_assistente] = lambda: object()
    monkeypatch.setattr(rota, "responde", responde_falso)
    return feitas


def _transacao(db, data, valor, tipo, categoria, usuario=USUARIO):
    db.linhas.append({"usuario_id": usuario.id, "extrato_id": None, "data": data, "historico": "X",
                      "contraparte": "LOJA", "valor": Decimal(valor), "tipo": tipo, "meio": "pix",
                      "banco": "nubank", "categoria": categoria, "origem_categoria": "regra"})


def test_painel_sem_dados():
    r = TestClient(app).get("/api/painel").json()
    assert r["tem_dados"] is False and r["grafico"] is None


def test_painel_com_dados(db):
    _transacao(db, date(2024, 1, 5), "1000.00", "entrada", "receitas")
    _transacao(db, date(2024, 2, 5), "3000.00", "entrada", "receitas")
    _transacao(db, date(2024, 2, 6), "-200.00", "saida", "mercado")
    _transacao(db, date(2024, 2, 7), "-500.00", "saida", "financeiro")   # pagar fatura não é despesa
    _transacao(db, date(2024, 2, 8), "-999.00", "saida", "mercado", OUTRO)  # de outro usuário
    r = TestClient(app).get("/api/painel").json()
    assert (r["mes"], r["receitas"], r["despesas"], r["saldo"]) == ("fev/24", 3000.0, 200.0, 2800.0)
    assert r["grafico"]["rotulos"][-2:] == ["jan/24", "fev/24"]


def test_chat_cria_conversa_e_guarda_as_mensagens(db, chamadas):
    _transacao(db, date(2024, 1, 5), "-10.00", "saida", "mercado")
    cliente = TestClient(app)
    r = cliente.post("/api/chat", json={"mensagem": "quanto gastei de mercado?"}).json()
    assert r["resposta"]["texto"] == "resposta para: quanto gastei de mercado?"
    assert r["resposta"]["grafico"]["titulo"] == "Teste"
    assert chamadas[0]["linhas"] == 1 and chamadas[0]["historico"] == []
    [conversa] = cliente.get("/api/conversas").json()
    assert conversa["id"] == r["conversa_id"] and conversa["titulo"] == "quanto gastei de mercado?"

    # continuar a conversa manda o histórico
    cliente.post("/api/chat", json={"mensagem": "e transporte?", "conversa_id": r["conversa_id"]})
    assert [m["texto"] for m in chamadas[1]["historico"]] == [
        "quanto gastei de mercado?", "resposta para: quanto gastei de mercado?"]
    mensagens = cliente.get(f"/api/conversas/{r['conversa_id']}/mensagens").json()
    assert [m["papel"] for m in mensagens] == ["usuario", "agente", "usuario", "agente"]


def test_titulo_longo_e_cortado(chamadas):
    r = TestClient(app).post("/api/chat", json={"mensagem": "a" * 200}).json()
    [c] = TestClient(app).get("/api/conversas").json()
    assert len(c["titulo"]) == 60 and c["titulo"].endswith("…") and r["conversa_id"] == c["id"]


def test_conversa_de_outro_usuario_da_404(chamadas, logado_como):
    cid = TestClient(app).post("/api/chat", json={"mensagem": "oi"}).json()["conversa_id"]
    logado_como(OUTRO)
    cliente = TestClient(app)
    assert cliente.get(f"/api/conversas/{cid}/mensagens").status_code == 404
    assert cliente.post("/api/chat", json={"mensagem": "oi", "conversa_id": cid}).status_code == 404
    assert cliente.delete(f"/api/conversas/{cid}").status_code == 404
    assert cliente.get("/api/conversas").json() == []


def test_erro_do_assistente_nao_grava_nada(db, monkeypatch):
    def quebra(*_a, **_k):
        raise RuntimeError("Gemini fora do ar")

    app.dependency_overrides[modelo_do_assistente] = lambda: object()
    monkeypatch.setattr(rota, "responde", quebra)
    r = TestClient(app).post("/api/chat", json={"mensagem": "oi"})
    assert r.status_code == 502
    assert db.mensagens_ == []


def test_mensagem_vazia_da_422_ou_400(chamadas):
    cliente = TestClient(app)
    assert cliente.post("/api/chat", json={"mensagem": ""}).status_code == 422
    assert cliente.post("/api/chat", json={"mensagem": "   "}).status_code == 400
