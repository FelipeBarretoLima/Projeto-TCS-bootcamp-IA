"""Usuários e banco falsos para os testes da API (nenhum dado real, nenhuma conexão)."""

from collections import Counter
from datetime import datetime, timezone
from itertools import count
from uuid import UUID, uuid4

from api.autenticacao import Usuario
from banco.deduplicacao import separa_novas
from banco.repositorio import ExtratoRepetido, Gravacao

USUARIO = Usuario(UUID("00000000-0000-4000-8000-000000000001"), "teste@exemplo.invalid", "Teste")
OUTRO = Usuario(UUID("00000000-0000-4000-8000-000000000002"), "outro@exemplo.invalid", "Outro")


class BancoFalso:
    """Mesma interface de banco.repositorio.Banco, em memória."""

    def __init__(self):
        self.usuarios, self.extratos, self.linhas = {}, {}, []
        self.conversas, self.mensagens_ = {}, []
        self._ids = count(1)

    def garante_usuario(self, usuario_id, email, nome=""):
        self.usuarios.setdefault(usuario_id, {"id": usuario_id, "email": email, "nome": nome})

    def grava_extrato(self, usuario_id, *, nome_arquivo, hash_arquivo, parser, periodo_inicio,
                      periodo_fim, transacoes):
        if any(e["usuario_id"] == usuario_id and e["hash_arquivo"] == hash_arquivo for e in self.extratos.values()):
            raise ExtratoRepetido
        existentes = [t for t in self.linhas if t["usuario_id"] == usuario_id]
        gravar, repetidas = separa_novas(existentes, transacoes)
        eid = uuid4()
        bancos = Counter(t["banco"] for t in transacoes)
        self.extratos[eid] = {"id": eid, "usuario_id": usuario_id, "nome_arquivo": nome_arquivo,
                              "hash_arquivo": hash_arquivo, "banco": bancos.most_common(1)[0][0],
                              "parser": parser, "periodo_inicio": periodo_inicio, "periodo_fim": periodo_fim,
                              "linhas_gravadas": len(gravar), "enviado_em": datetime.now(timezone.utc)}
        self.linhas += [{**t, "usuario_id": usuario_id, "extrato_id": eid} for t in gravar]
        return Gravacao(eid, len(gravar), repetidas)

    def lista_extratos(self, usuario_id):
        return [{k: v for k, v in e.items() if k not in ("usuario_id", "hash_arquivo")}
                for e in self.extratos.values() if e["usuario_id"] == usuario_id]

    def apaga_extrato(self, usuario_id, extrato_id):
        e = self.extratos.get(extrato_id)
        if not e or e["usuario_id"] != usuario_id:
            return False
        del self.extratos[extrato_id]
        self.linhas = [t for t in self.linhas if t["extrato_id"] != extrato_id]
        return True

    def transacoes(self, usuario_id):
        return [t for t in self.linhas if t["usuario_id"] == usuario_id]

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
        m = {"id": next(self._ids), "conversa_id": conversa_id, "papel": papel, "texto": texto,
             "grafico": grafico, "criada_em": datetime.now(timezone.utc)}
        self.mensagens_.append(m)
        self.conversas[conversa_id]["atualizada_em"] = m["criada_em"]
        return {k: v for k, v in m.items() if k != "conversa_id"}
