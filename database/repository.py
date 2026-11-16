"""Database reads and writes. Every function receives the user id and filters by it.

`Database` wraps an open connection; whoever opens the connection decides the commit (in the API,
each request is one transaction: on error, nothing is saved).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .deduplication import split_new_with_ids

TRANSACTION_COLUMNS = ("data", "historico", "contraparte", "valor", "tipo", "meio", "banco",
                       "categoria", "origem_categoria")
# original text encrypted by the API (api/cipher.py); optional in each transaction
ORIGINAL_COLUMN = "original_cifrado"
# anonymized fields copied from the transaction to public.correcoes (parser contract, without id_usuario)
_CORRECTION_FIELDS = ("data", "historico", "contraparte", "valor", "tipo", "meio", "banco")
# fixed lock key (pg_advisory_xact_lock) that prevents two retrainings at the same time
_RETRAINING_LOCK = 7_242_001


class DuplicateStatement(Exception):
    """The same file (same hash) was already uploaded by this user."""


class ConversationDeleted(Exception):
    """The conversation was deleted while the answer was being generated."""


@dataclass(frozen=True)
class SaveResult:
    statement_id: UUID
    saved: int
    duplicates: int


class Database:
    def __init__(self, connection: psycopg.Connection):
        self.con = connection

    def commit(self) -> None:
        """Commit before the end of the request (e.g. the correction must be saved before the retraining)."""
        self.con.commit()

    def _all(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        with self.con.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, args).fetchall()

    def _one(self, sql: str, *args: Any) -> dict[str, Any] | None:
        with self.con.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, args).fetchone()

    # --- users ---

    def ensure_user(self, user_id: UUID, email: str, name: str = "") -> None:
        """The profile is created by the sign-up trigger; this covers accounts created before the tables."""
        self.con.execute(
            "insert into public.usuarios (id, email, nome) values (%s, %s, %s) on conflict (id) do nothing",
            (user_id, email, name))

    def profile(self, user_id: UUID) -> dict[str, Any] | None:
        return self._one("select id, nome, email, criado_em from public.usuarios where id = %s", user_id)

    def rename_user(self, user_id: UUID, name: str) -> None:
        self.con.execute("update public.usuarios set nome = %s where id = %s", (name, user_id))

    def delete_account(self, user_id: UUID) -> None:
        """Deletes the login in Supabase Auth; profile, statements, transactions and conversations cascade."""
        self.con.execute("delete from auth.users where id = %s", (user_id,))

    # --- statements and transactions ---

    def save_statement(self, user_id: UUID, *, nome_arquivo: str, hash_arquivo: str, parser: str,
                       periodo_inicio: date | None, periodo_fim: date | None,
                       transactions: list[dict[str, Any]]) -> SaveResult:
        """Saves the statement and only the transactions not yet in the database (see deduplication.py)."""
        # Imports of the same user queue up until the commit: without this, two overlapping statements
        # sent at the same time read the database before the other one saved, and the duplicates went in
        # twice. The lock is released at the end of the transaction; different users do not wait for each other.
        self.con.execute("select pg_advisory_xact_lock(hashtextextended(%s::text, 0))", (str(user_id),))
        if self._one("select 1 from public.extratos where usuario_id = %s and hash_arquivo = %s",
                     user_id, hash_arquivo):
            raise DuplicateStatement
        existing: list[dict[str, Any]] = []
        if transactions:
            dates = [t["data"] for t in transactions]
            existing = self._all(
                "select id, banco, data, valor, tipo, meio, historico, contraparte from public.transacoes "
                "where usuario_id = %s and banco = any(%s) and data between %s and %s order by id",
                user_id, sorted({t["banco"] for t in transactions}), min(dates), max(dates))
        to_save, duplicate_ids = split_new_with_ids(existing, transactions)
        banks = Counter(t["banco"] for t in transactions)
        bank = banks.most_common(1)[0][0] if banks else ""
        try:
            statement_id = self._one(
                "insert into public.extratos (usuario_id, nome_arquivo, hash_arquivo, banco, parser, "
                "periodo_inicio, periodo_fim, linhas_gravadas) values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
                user_id, nome_arquivo, hash_arquivo, bank, parser, periodo_inicio, periodo_fim, len(to_save))["id"]
        except psycopg.errors.UniqueViolation:
            # the same file arrived twice at the same time (e.g. two tabs): the other upload won
            raise DuplicateStatement from None
        if to_save:
            with self.con.cursor() as cur:
                columns = (*TRANSACTION_COLUMNS, ORIGINAL_COLUMN)
                cur.executemany(
                    f"insert into public.transacoes (usuario_id, extrato_id, {', '.join(columns)}) "
                    f"values (%s, %s, {', '.join(['%s'] * len(columns))})",
                    [(user_id, statement_id, *(t[c] for c in TRANSACTION_COLUMNS), t.get(ORIGINAL_COLUMN))
                     for t in to_save])
        # links: the ones saved now and the duplicates (already in the database from another statement)
        self.con.execute(
            "insert into public.extrato_transacoes (extrato_id, transacao_id) "
            "select %s, id from public.transacoes where extrato_id = %s",
            (statement_id, statement_id))
        if duplicate_ids:
            self.con.execute(
                "insert into public.extrato_transacoes (extrato_id, transacao_id) "
                "select %s, unnest(%s::bigint[]) on conflict do nothing",
                (statement_id, duplicate_ids))
        return SaveResult(statement_id, len(to_save), len(duplicate_ids))

    def list_statements(self, user_id: UUID) -> list[dict[str, Any]]:
        return self._all(
            "select id, nome_arquivo, banco, parser, periodo_inicio, periodo_fim, linhas_gravadas, enviado_em "
            "from public.extratos where usuario_id = %s order by enviado_em desc", user_id)

    def delete_statement(self, user_id: UUID, statement_id: UUID) -> bool:
        """Deletes the statement and the transactions only it brought. False if it is not the user's.

        A transaction that another statement also brought (overlapping periods) is not deleted: it
        moves to that other statement, which stays imported.
        """
        if not self._one("select 1 from public.extratos where id = %s and usuario_id = %s",
                         statement_id, user_id):
            return False
        heirs = self._all(
            "update public.transacoes t set extrato_id = o.extrato_id "
            "from (select distinct on (et.transacao_id) et.transacao_id, et.extrato_id "
            "      from public.extrato_transacoes et "
            "      join public.extratos e on e.id = et.extrato_id and e.usuario_id = %s "
            "      where et.extrato_id <> %s and et.transacao_id in "
            "            (select id from public.transacoes where extrato_id = %s) "
            "      order by et.transacao_id, e.enviado_em) o "
            "where t.id = o.transacao_id returning t.extrato_id",
            user_id, statement_id, statement_id)
        if heirs:
            self.con.execute(
                "update public.extratos e set linhas_gravadas = "
                "(select count(*) from public.transacoes t where t.extrato_id = e.id) where e.id = any(%s)",
                (sorted({h["extrato_id"] for h in heirs}),))
        cur = self.con.execute("delete from public.extratos where id = %s and usuario_id = %s",
                               (statement_id, user_id))
        return cur.rowcount > 0

    def transactions(self, user_id: UUID) -> list[dict[str, Any]]:
        return self._all(
            "select data, historico, contraparte, valor, tipo, meio, banco, categoria from public.transacoes "
            "where usuario_id = %s order by data, id", user_id)

    def transaction_period(self, user_id: UUID) -> tuple[date | None, date | None]:
        """Date of the user's first and last transaction (None, None if there are none)."""
        row = self._one("select min(data) as primeira, max(data) as ultima from public.transacoes "
                        "where usuario_id = %s", user_id)
        return row["primeira"], row["ultima"]

    def find_transactions(self, user_id: UUID, *, start: date | None = None, end: date | None = None,
                          categoria: str | None = None, uncategorized: bool = False) -> list[dict[str, Any]]:
        """The user's transactions for the Extrato tab, from the most recent to the oldest.

        Optional filters: period (inclusive) and one category, or only the uncategorized ones.
        Includes the encrypted original (only the Extrato tab decrypts it; `transactions()`, used by
        the chat, does not read it).
        """
        conditions, args = ["usuario_id = %s"], [user_id]
        if start is not None:
            conditions.append("data >= %s")
            args.append(start)
        if end is not None:
            conditions.append("data <= %s")
            args.append(end)
        if uncategorized:
            conditions.append("categoria is null")
        elif categoria is not None:
            conditions.append("categoria = %s")
            args.append(categoria)
        return self._all(
            "select id, data, historico, contraparte, valor, tipo, meio, banco, categoria, original_cifrado "
            f"from public.transacoes where {' and '.join(conditions)} order by data desc, id desc", *args)

    def set_category(self, user_id: UUID, transaction_id: int, categoria: str | None) -> bool:
        """Correction made by the user (origin "usuario"); None = uncategorized. False if not theirs.

        The correction also goes to public.correcoes (anonymized fields only), where it survives the
        deletion of the statement. Going back to "uncategorized" undoes the correction in both tables.
        """
        row = self._one(
            "update public.transacoes set categoria = %s, "
            "origem_categoria = case when %s::text is null then null else 'usuario' end, "
            "corrigida_em = case when %s::text is null then null else now() end "
            "where id = %s and usuario_id = %s "
            "returning data, historico, contraparte, valor, tipo, meio, banco",
            categoria, categoria, categoria, transaction_id, user_id)
        if row is None:
            return False
        if categoria is None:
            self.con.execute("delete from public.correcoes where transacao_id = %s", (transaction_id,))
            return True
        fields = tuple(row[c] for c in _CORRECTION_FIELDS)
        # the same transaction corrected before in an already deleted statement and imported again:
        # the old correction (without a transaction) gives way to this one, so it is not counted twice in training
        self.con.execute(
            "delete from public.correcoes where usuario_id = %s and transacao_id is null and "
            f"({', '.join(_CORRECTION_FIELDS)}) = ({', '.join(['%s'] * len(_CORRECTION_FIELDS))})",
            (user_id, *fields))
        self.con.execute(
            f"insert into public.correcoes (usuario_id, transacao_id, {', '.join(_CORRECTION_FIELDS)}, categoria) "
            f"values (%s, %s, {', '.join(['%s'] * len(_CORRECTION_FIELDS))}, %s) "
            "on conflict (transacao_id) do update set categoria = excluded.categoria, corrigida_em = now()",
            (user_id, transaction_id, *fields, categoria))
        return True

    # --- classifier retraining (api/services/retraining.py) ---
    # Exception to the "every function filters by the user" rule: there is a single model, trained with
    # everyone's corrections. Only anonymized fields leave here (never original_cifrado).

    def corrections_for_training(self) -> list[dict[str, Any]]:
        """All the users' corrections, as training examples (parser contract + category).

        They come from public.correcoes: they include the ones from already deleted statements.
        """
        return self._all(
            "select data, historico, contraparte, valor, tipo, meio, banco, categoria, corrigida_em "
            "from public.correcoes order by corrigida_em, id")

    def corrections_since_last_training(self) -> int:
        """Corrections made after the start of the last finished retraining attempt, successful or
        failed (all of them, if there was never one).

        Counting only since the last "ok" made every correction after an error (e.g. missing base CSV)
        trigger another retraining. Now, after an error, 15 more corrections are needed; the next
        retraining uses all corrections, including the ones before the error.
        """
        return self._one(
            "select count(*) as n from public.correcoes "
            "where corrigida_em > coalesce((select max(iniciado_em) from public.treinos_modelo "
            "where status <> 'rodando'), '-infinity')")["n"]

    def training_running(self) -> bool:
        """Is a retraining in progress? (a "rodando" older than 30 min is considered stuck)"""
        return self._one(
            "select 1 from public.treinos_modelo where status = 'rodando' "
            "and iniciado_em > now() - interval '30 minutes'") is not None

    def start_training(self) -> int:
        return self._one("insert into public.treinos_modelo default values returning id")["id"]

    def start_training_if_free(self) -> int | None:
        """Records a "rodando" retraining, or None if there already is one. Atomic across processes.

        Without the lock, two APIs (or the API and `python -m api.retrain`) could check "none running"
        at the same time and start two retrainings. The lock holds until the caller's commit.
        """
        self.con.execute("select pg_advisory_xact_lock(%s)", (_RETRAINING_LOCK,))
        if self.training_running():
            return None
        return self.start_training()

    def finish_training(self, training_id: int, *, status: str, correcoes: int = 0, linhas_treino: int = 0,
                        acerto_correcoes_antes: float | None = None, acerto_correcoes_depois: float | None = None,
                        acerto_base_depois: float | None = None, mensagem: str = "") -> None:
        self.con.execute(
            "update public.treinos_modelo set concluido_em = now(), status = %s, correcoes = %s, "
            "linhas_treino = %s, acerto_correcoes_antes = %s, acerto_correcoes_depois = %s, "
            "acerto_base_depois = %s, mensagem = %s where id = %s",
            (status, correcoes, linhas_treino, acerto_correcoes_antes, acerto_correcoes_depois,
             acerto_base_depois, mensagem[:500], training_id))

    def trainings(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._all("select * from public.treinos_modelo order by iniciado_em desc limit %s", limit)

    # --- assistant conversations ---

    def list_conversations(self, user_id: UUID) -> list[dict[str, Any]]:
        return self._all(
            "select id, titulo, criada_em, atualizada_em from public.conversas "
            "where usuario_id = %s order by atualizada_em desc", user_id)

    def create_conversation(self, user_id: UUID, title: str) -> UUID:
        return self._one("insert into public.conversas (usuario_id, titulo) values (%s, %s) returning id",
                         user_id, title)["id"]

    def conversation_belongs_to_user(self, user_id: UUID, conversation_id: UUID) -> bool:
        return self._one("select 1 from public.conversas where id = %s and usuario_id = %s",
                         conversation_id, user_id) is not None

    def rename_conversation(self, user_id: UUID, conversation_id: UUID, title: str) -> bool:
        cur = self.con.execute("update public.conversas set titulo = %s where id = %s and usuario_id = %s",
                               (title, conversation_id, user_id))
        return cur.rowcount > 0

    def delete_conversation(self, user_id: UUID, conversation_id: UUID) -> bool:
        cur = self.con.execute("delete from public.conversas where id = %s and usuario_id = %s",
                               (conversation_id, user_id))
        return cur.rowcount > 0

    def messages(self, conversation_id: UUID) -> list[dict[str, Any]]:
        return self._all(
            "select id, papel, texto, grafico, criada_em from public.mensagens "
            "where conversa_id = %s order by criada_em, id", conversation_id)

    def save_message(self, conversation_id: UUID, role: str, text: str,
                     chart: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return self._one(
                "insert into public.mensagens (conversa_id, papel, texto, grafico) values (%s, %s, %s, %s) "
                "returning id, papel, texto, grafico, criada_em",
                conversation_id, role, text, json.dumps(chart, default=_json_default) if chart else None)
        except psycopg.errors.ForeignKeyViolation:
            raise ConversationDeleted from None


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(type(value))
