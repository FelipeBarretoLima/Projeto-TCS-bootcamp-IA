"""Fake users and database for the API tests (no real data, no connection)."""

from collections import Counter
from datetime import datetime, timezone
from itertools import count
from uuid import UUID, uuid4

from api.auth import User
from database.deduplication import split_new_with_ids
from database.repository import ConversationDeleted, DuplicateStatement, SaveResult

USER = User(UUID("00000000-0000-4000-8000-000000000001"), "teste@exemplo.invalid", "Teste")
OTHER_USER = User(UUID("00000000-0000-4000-8000-000000000002"), "outro@exemplo.invalid", "Outro")


class FakeDatabase:
    """Same interface as database.repository.Database, in memory."""

    def __init__(self):
        self.users, self.statements, self.rows = {}, {}, []
        self.links: set[tuple[UUID, int]] = set()  # (statement, transaction): who brought each transaction
        self.conversations, self.messages_ = {}, []
        self._ids = count(1)
        self._transaction_ids = count(1)
        self.trainings_: list[dict] = []
        self.corrections_: list[dict] = []  # public.correcoes: they survive the deletion of the statement
        self.commits = 0

    def ensure_user(self, user_id, email, name=""):
        self.users.setdefault(user_id, {"id": user_id, "email": email, "nome": name})

    def save_statement(self, user_id, *, nome_arquivo, hash_arquivo, parser, periodo_inicio,
                       periodo_fim, transactions):
        if any(e["usuario_id"] == user_id and e["hash_arquivo"] == hash_arquivo for e in self.statements.values()):
            raise DuplicateStatement
        existing = [t for t in self.rows if t["usuario_id"] == user_id]
        to_save, duplicate_ids = split_new_with_ids(existing, transactions)
        sid = uuid4()
        banks = Counter(t["banco"] for t in transactions)
        self.statements[sid] = {"id": sid, "usuario_id": user_id, "nome_arquivo": nome_arquivo,
                                "hash_arquivo": hash_arquivo, "banco": banks.most_common(1)[0][0],
                                "parser": parser, "periodo_inicio": periodo_inicio, "periodo_fim": periodo_fim,
                                "linhas_gravadas": len(to_save), "enviado_em": datetime.now(timezone.utc)}
        new = [{**t, "id": next(self._transaction_ids), "usuario_id": user_id, "extrato_id": sid} for t in to_save]
        self.rows += new
        self.links |= {(sid, t["id"]) for t in new} | {(sid, tid) for tid in duplicate_ids}
        return SaveResult(sid, len(to_save), len(duplicate_ids))

    def list_statements(self, user_id):
        return [{k: v for k, v in e.items() if k not in ("usuario_id", "hash_arquivo")}
                for e in self.statements.values() if e["usuario_id"] == user_id]

    def delete_statement(self, user_id, statement_id):
        e = self.statements.get(statement_id)
        if not e or e["usuario_id"] != user_id:
            return False
        # the ones another statement also brought move to it (the oldest one); the others go away
        for t in self.rows:
            if t["extrato_id"] != statement_id:
                continue
            others = [self.statements[x] for x, tid in self.links if tid == t["id"] and x != statement_id]
            if others:
                heir = min(others, key=lambda o: o["enviado_em"])
                t["extrato_id"] = heir["id"]
                heir["linhas_gravadas"] += 1
        del self.statements[statement_id]
        self.links = {(x, tid) for x, tid in self.links if x != statement_id}
        leaving = {t["id"] for t in self.rows if t["extrato_id"] == statement_id}
        for c in self.corrections_:  # on delete set null: the correction stays valid
            if c["transacao_id"] in leaving:
                c["transacao_id"] = None
        self.rows = [t for t in self.rows if t["extrato_id"] != statement_id]
        return True

    def transactions(self, user_id):
        return [t for t in self.rows if t["usuario_id"] == user_id]

    def transaction_period(self, user_id):
        dates = [t["data"] for t in self.rows if t["usuario_id"] == user_id]
        return (min(dates), max(dates)) if dates else (None, None)

    def find_transactions(self, user_id, *, start=None, end=None, categoria=None, uncategorized=False):
        def matches(t):
            return (t["usuario_id"] == user_id
                    and (start is None or t["data"] >= start)
                    and (end is None or t["data"] <= end)
                    and (t["categoria"] is None if uncategorized
                         else categoria is None or t["categoria"] == categoria))
        found = [t for t in self.rows if matches(t)]
        return sorted(found, key=lambda t: t["data"], reverse=True)

    def list_conversations(self, user_id):
        return sorted((c for c in self.conversations.values() if c["usuario_id"] == user_id),
                      key=lambda c: c["atualizada_em"], reverse=True)

    def create_conversation(self, user_id, title):
        cid, now = uuid4(), datetime.now(timezone.utc)
        self.conversations[cid] = {"id": cid, "usuario_id": user_id, "titulo": title,
                                   "criada_em": now, "atualizada_em": now}
        return cid

    def conversation_belongs_to_user(self, user_id, conversation_id):
        c = self.conversations.get(conversation_id)
        return bool(c and c["usuario_id"] == user_id)

    def rename_conversation(self, user_id, conversation_id, title):
        if not self.conversation_belongs_to_user(user_id, conversation_id):
            return False
        self.conversations[conversation_id]["titulo"] = title
        return True

    def set_category(self, user_id, transaction_id, categoria):
        for t in self.rows:
            if t.get("id") == transaction_id and t["usuario_id"] == user_id:
                now = datetime.now(timezone.utc)
                t["categoria"], t["origem_categoria"] = categoria, ("usuario" if categoria else None)
                t["corrigida_em"] = now if categoria else None
                fields = {k: t[k] for k in ("data", "historico", "contraparte", "valor", "tipo", "meio", "banco")}
                # as in the real database: undo, replace the orphan correction of the same transaction and upsert
                self.corrections_ = [c for c in self.corrections_ if c["transacao_id"] != transaction_id and not (
                    c["usuario_id"] == user_id and c["transacao_id"] is None
                    and {k: c[k] for k in fields} == fields)]
                if categoria:
                    self.corrections_.append({"usuario_id": user_id, "transacao_id": transaction_id, **fields,
                                              "categoria": categoria, "corrigida_em": now})
                return True
        return False

    def commit(self):
        self.commits += 1

    # --- retraining ---

    def corrections_for_training(self):
        fields = ("data", "historico", "contraparte", "valor", "tipo", "meio", "banco", "categoria", "corrigida_em")
        return [{k: c[k] for k in fields} for c in sorted(self.corrections_, key=lambda c: c["corrigida_em"])]

    def corrections_since_last_training(self):
        # since the last finished attempt (ok or error), as in the real database
        finished = [t["iniciado_em"] for t in self.trainings_ if t["status"] != "rodando"]
        since = max(finished) if finished else datetime.min.replace(tzinfo=timezone.utc)
        return sum(1 for c in self.corrections_ if c["corrigida_em"] > since)

    def training_running(self):
        return any(t["status"] == "rodando" for t in self.trainings_)

    def start_training(self):
        self.trainings_.append({"id": len(self.trainings_) + 1, "status": "rodando",
                                "iniciado_em": datetime.now(timezone.utc)})
        return len(self.trainings_)

    def start_training_if_free(self):
        return None if self.training_running() else self.start_training()

    def finish_training(self, training_id, **record):
        self.trainings_[training_id - 1].update(record)

    def trainings(self, limit=20):
        return list(reversed(self.trainings_))[:limit]

    def rename_user(self, user_id, name):
        if user_id in self.users:
            self.users[user_id]["nome"] = name

    def delete_account(self, user_id):
        self.users.pop(user_id, None)
        deleted = {e for e, x in self.statements.items() if x["usuario_id"] == user_id}
        self.statements = {e: x for e, x in self.statements.items() if e not in deleted}
        self.links = {(e, t) for e, t in self.links if e not in deleted}
        self.rows = [t for t in self.rows if t["usuario_id"] != user_id]
        self.corrections_ = [c for c in self.corrections_ if c["usuario_id"] != user_id]  # cascade (LGPD)
        conversations = {c for c, x in self.conversations.items() if x["usuario_id"] == user_id}
        self.conversations = {c: x for c, x in self.conversations.items() if c not in conversations}
        self.messages_ = [m for m in self.messages_ if m["conversa_id"] not in conversations]

    def delete_conversation(self, user_id, conversation_id):
        if not self.conversation_belongs_to_user(user_id, conversation_id):
            return False
        del self.conversations[conversation_id]
        self.messages_ = [m for m in self.messages_ if m["conversa_id"] != conversation_id]
        return True

    def messages(self, conversation_id):
        return [{k: v for k, v in m.items() if k != "conversa_id"} for m in self.messages_
                if m["conversa_id"] == conversation_id]

    def save_message(self, conversation_id, role, text, chart=None):
        if conversation_id not in self.conversations:
            raise ConversationDeleted
        m = {"id": next(self._ids), "conversa_id": conversation_id, "papel": role, "texto": text,
             "grafico": chart, "criada_em": datetime.now(timezone.utc)}
        self.messages_.append(m)
        self.conversations[conversation_id]["atualizada_em"] = m["criada_em"]
        return {k: v for k, v in m.items() if k != "conversa_id"}
