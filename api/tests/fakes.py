"""Usuários e banco falsos para os testes da API (nenhum dado real, nenhuma conexão)."""

from collections import Counter
from datetime import datetime, timezone
from itertools import count
from uuid import UUID, uuid4

from api.auth import Usuario
from database.deduplication import separa_novas_com_ids
from database.repository import ConversaApagada, ExtratoRepetido, Gravacao

USUARIO = Usuario(UUID("00000000-0000-4000-8000-000000000001"), "teste@exemplo.invalid", "Teste")
OUTRO = Usuario(UUID("00000000-0000-4000-8000-000000000002"), "outro@exemplo.invalid", "Outro")


class BancoFalso:
    """Mesma interface de database.repository.Banco, em memória."""

    def __init__(self):
        self.usuarios, self.extratos, self.linhas = {}, {}, []
        self.vinculos: set[tuple[UUID, int]] = set()  # (extrato, transação): quem trouxe cada transação
        self.conversas, self.mensagens_ = {}, []
        self._ids = count(1)
        self._ids_transacao = count(1)
        self.treinos_: list[dict] = []
        self.correcoes_: list[dict] = []  # public.correcoes: sobrevivem à exclusão do extrato
        self.confirmacoes = 0

    def garante_usuario(self, usuario_id, email, nome=""):
        self.usuarios.setdefault(usuario_id, {"id": usuario_id, "email": email, "nome": nome})

    def grava_extrato(self, usuario_id, *, nome_arquivo, hash_arquivo, parser, periodo_inicio,
                      periodo_fim, transacoes):
        if any(e["usuario_id"] == usuario_id and e["hash_arquivo"] == hash_arquivo for e in self.extratos.values()):
            raise ExtratoRepetido
        existentes = [t for t in self.linhas if t["usuario_id"] == usuario_id]
        gravar, ids_repetidas = separa_novas_com_ids(existentes, transacoes)
        eid = uuid4()
        bancos = Counter(t["banco"] for t in transacoes)
        self.extratos[eid] = {"id": eid, "usuario_id": usuario_id, "nome_arquivo": nome_arquivo,
                              "hash_arquivo": hash_arquivo, "banco": bancos.most_common(1)[0][0],
                              "parser": parser, "periodo_inicio": periodo_inicio, "periodo_fim": periodo_fim,
                              "linhas_gravadas": len(gravar), "enviado_em": datetime.now(timezone.utc)}
        novas = [{**t, "id": next(self._ids_transacao), "usuario_id": usuario_id, "extrato_id": eid} for t in gravar]
        self.linhas += novas
        self.vinculos |= {(eid, t["id"]) for t in novas} | {(eid, tid) for tid in ids_repetidas}
        return Gravacao(eid, len(gravar), len(ids_repetidas))

    def lista_extratos(self, usuario_id):
        return [{k: v for k, v in e.items() if k not in ("usuario_id", "hash_arquivo")}
                for e in self.extratos.values() if e["usuario_id"] == usuario_id]

    def apaga_extrato(self, usuario_id, extrato_id):
        e = self.extratos.get(extrato_id)
        if not e or e["usuario_id"] != usuario_id:
            return False
        # as que outro extrato também trouxe passam para ele (o mais antigo); as outras saem
        for t in self.linhas:
            if t["extrato_id"] != extrato_id:
                continue
            outros = [self.extratos[x] for x, tid in self.vinculos if tid == t["id"] and x != extrato_id]
            if outros:
                herdeiro = min(outros, key=lambda o: o["enviado_em"])
                t["extrato_id"] = herdeiro["id"]
                herdeiro["linhas_gravadas"] += 1
        del self.extratos[extrato_id]
        self.vinculos = {(x, tid) for x, tid in self.vinculos if x != extrato_id}
        saem = {t["id"] for t in self.linhas if t["extrato_id"] == extrato_id}
        for c in self.correcoes_:  # on delete set null: a correção continua valendo
            if c["transacao_id"] in saem:
                c["transacao_id"] = None
        self.linhas = [t for t in self.linhas if t["extrato_id"] != extrato_id]
        return True

    def transacoes(self, usuario_id):
        return [t for t in self.linhas if t["usuario_id"] == usuario_id]

    def periodo_transacoes(self, usuario_id):
        datas = [t["data"] for t in self.linhas if t["usuario_id"] == usuario_id]
        return (min(datas), max(datas)) if datas else (None, None)

    def busca_transacoes(self, usuario_id, *, inicio=None, fim=None, categoria=None, sem_categoria=False):
        def passa(t):
            return (t["usuario_id"] == usuario_id
                    and (inicio is None or t["data"] >= inicio)
                    and (fim is None or t["data"] <= fim)
                    and (t["categoria"] is None if sem_categoria
                         else categoria is None or t["categoria"] == categoria))
        achadas = [t for t in self.linhas if passa(t)]
        return sorted(achadas, key=lambda t: t["data"], reverse=True)

    def lista_conversas(self, usuario_id):
        return sorted((c for c in self.conversas.values() if c["usuario_id"] == usuario_id),
                      key=lambda c: c["atualizada_em"], reverse=True)

    def cria_conversa(self, usuario_id, titulo):
        cid, agora = uuid4(), datetime.now(timezone.utc)
        self.conversas[cid] = {"id": cid, "usuario_id": usuario_id, "titulo": titulo,
                               "criada_em": agora, "atualizada_em": agora}
        return cid

    def conversa_e_do_usuario(self, usuario_id, conversa_id):
        c = self.conversas.get(conversa_id)
        return bool(c and c["usuario_id"] == usuario_id)

    def renomeia_conversa(self, usuario_id, conversa_id, titulo):
        if not self.conversa_e_do_usuario(usuario_id, conversa_id):
            return False
        self.conversas[conversa_id]["titulo"] = titulo
        return True

    def muda_categoria(self, usuario_id, transacao_id, categoria):
        for t in self.linhas:
            if t.get("id") == transacao_id and t["usuario_id"] == usuario_id:
                agora = datetime.now(timezone.utc)
                t["categoria"], t["origem_categoria"] = categoria, ("usuario" if categoria else None)
                t["corrigida_em"] = agora if categoria else None
                campos = {k: t[k] for k in ("data", "historico", "contraparte", "valor", "tipo", "meio", "banco")}
                # como no banco real: desfaz, troca a correção órfã da mesma transação e faz o upsert
                self.correcoes_ = [c for c in self.correcoes_ if c["transacao_id"] != transacao_id and not (
                    c["usuario_id"] == usuario_id and c["transacao_id"] is None
                    and {k: c[k] for k in campos} == campos)]
                if categoria:
                    self.correcoes_.append({"usuario_id": usuario_id, "transacao_id": transacao_id, **campos,
                                            "categoria": categoria, "corrigida_em": agora})
                return True
        return False

    def confirma(self):
        self.confirmacoes += 1

    # --- retreino ---

    def correcoes_para_treino(self):
        campos = ("data", "historico", "contraparte", "valor", "tipo", "meio", "banco", "categoria", "corrigida_em")
        return [{k: c[k] for k in campos} for c in sorted(self.correcoes_, key=lambda c: c["corrigida_em"])]

    def correcoes_desde_ultimo_treino(self):
        # desde a última tentativa concluída (ok ou erro), como no banco real
        concluidos = [t["iniciado_em"] for t in self.treinos_ if t["status"] != "rodando"]
        desde = max(concluidos) if concluidos else datetime.min.replace(tzinfo=timezone.utc)
        return sum(1 for c in self.correcoes_ if c["corrigida_em"] > desde)

    def treino_rodando(self):
        return any(t["status"] == "rodando" for t in self.treinos_)

    def inicia_treino(self):
        self.treinos_.append({"id": len(self.treinos_) + 1, "status": "rodando",
                              "iniciado_em": datetime.now(timezone.utc)})
        return len(self.treinos_)

    def inicia_treino_se_livre(self):
        return None if self.treino_rodando() else self.inicia_treino()

    def conclui_treino(self, treino_id, **registro):
        self.treinos_[treino_id - 1].update(registro)

    def treinos(self, limite=20):
        return list(reversed(self.treinos_))[:limite]

    def muda_nome(self, usuario_id, nome):
        if usuario_id in self.usuarios:
            self.usuarios[usuario_id]["nome"] = nome

    def apaga_conta(self, usuario_id):
        self.usuarios.pop(usuario_id, None)
        apagados = {e for e, x in self.extratos.items() if x["usuario_id"] == usuario_id}
        self.extratos = {e: x for e, x in self.extratos.items() if e not in apagados}
        self.vinculos = {(e, t) for e, t in self.vinculos if e not in apagados}
        self.linhas = [t for t in self.linhas if t["usuario_id"] != usuario_id]
        self.correcoes_ = [c for c in self.correcoes_ if c["usuario_id"] != usuario_id]  # cascata (LGPD)
        conversas = {c for c, x in self.conversas.items() if x["usuario_id"] == usuario_id}
        self.conversas = {c: x for c, x in self.conversas.items() if c not in conversas}
        self.mensagens_ = [m for m in self.mensagens_ if m["conversa_id"] not in conversas]

    def apaga_conversa(self, usuario_id, conversa_id):
        if not self.conversa_e_do_usuario(usuario_id, conversa_id):
            return False
        del self.conversas[conversa_id]
        self.mensagens_ = [m for m in self.mensagens_ if m["conversa_id"] != conversa_id]
        return True

    def mensagens(self, conversa_id):
        return [{k: v for k, v in m.items() if k != "conversa_id"} for m in self.mensagens_
                if m["conversa_id"] == conversa_id]

    def grava_mensagem(self, conversa_id, papel, texto, grafico=None):
        if conversa_id not in self.conversas:
            raise ConversaApagada
        m = {"id": next(self._ids), "conversa_id": conversa_id, "papel": papel, "texto": texto,
             "grafico": grafico, "criada_em": datetime.now(timezone.utc)}
        self.mensagens_.append(m)
        self.conversas[conversa_id]["atualizada_em"] = m["criada_em"]
        return {k: v for k, v in m.items() if k != "conversa_id"}
