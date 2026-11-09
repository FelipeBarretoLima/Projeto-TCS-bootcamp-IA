"""Leitura e gravação no banco. Toda função recebe o id do usuário e filtra por ele.

`Banco` envolve uma conexão aberta; quem abre a conexão decide o commit (na API, cada requisição
é uma transação: deu erro, nada fica gravado).
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

from .deduplicacao import separa_novas

COLUNAS_TRANSACAO = ("data", "historico", "contraparte", "valor", "tipo", "meio", "banco",
                     "categoria", "origem_categoria")


class ExtratoRepetido(Exception):
    """O mesmo arquivo (mesmo hash) já foi enviado por este usuário."""


@dataclass(frozen=True)
class Gravacao:
    extrato_id: UUID
    gravadas: int
    repetidas: int


class Banco:
    def __init__(self, conexao: psycopg.Connection):
        self.con = conexao

    def _todas(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        with self.con.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, args).fetchall()

    def _uma(self, sql: str, *args: Any) -> dict[str, Any] | None:
        with self.con.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, args).fetchone()

    # --- usuários ---

    def garante_usuario(self, usuario_id: UUID, email: str, nome: str = "") -> None:
        """O perfil nasce pelo gatilho do cadastro; isto cobre contas criadas antes das tabelas."""
        self.con.execute(
            "insert into public.usuarios (id, email, nome) values (%s, %s, %s) on conflict (id) do nothing",
            (usuario_id, email, nome))

    def perfil(self, usuario_id: UUID) -> dict[str, Any] | None:
        return self._uma("select id, nome, email, criado_em from public.usuarios where id = %s", usuario_id)

    # --- extratos e transações ---

    def grava_extrato(self, usuario_id: UUID, *, nome_arquivo: str, hash_arquivo: str, parser: str,
                      periodo_inicio: date | None, periodo_fim: date | None,
                      transacoes: list[dict[str, Any]]) -> Gravacao:
        """Grava o extrato e só as transações que ainda não estão no banco (ver deduplicacao.py)."""
        if self._uma("select 1 from public.extratos where usuario_id = %s and hash_arquivo = %s",
                     usuario_id, hash_arquivo):
            raise ExtratoRepetido
        existentes: list[dict[str, Any]] = []
        if transacoes:
            datas = [t["data"] for t in transacoes]
            existentes = self._todas(
                "select banco, data, valor, tipo, meio, historico, contraparte from public.transacoes "
                "where usuario_id = %s and banco = any(%s) and data between %s and %s",
                usuario_id, sorted({t["banco"] for t in transacoes}), min(datas), max(datas))
        gravar, repetidas = separa_novas(existentes, transacoes)
        bancos = Counter(t["banco"] for t in transacoes)
        banco = bancos.most_common(1)[0][0] if bancos else ""
        extrato_id = self._uma(
            "insert into public.extratos (usuario_id, nome_arquivo, hash_arquivo, banco, parser, "
            "periodo_inicio, periodo_fim, linhas_gravadas) values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
            usuario_id, nome_arquivo, hash_arquivo, banco, parser, periodo_inicio, periodo_fim, len(gravar))["id"]
        if gravar:
            with self.con.cursor() as cur:
                cur.executemany(
                    f"insert into public.transacoes (usuario_id, extrato_id, {', '.join(COLUNAS_TRANSACAO)}) "
                    f"values (%s, %s, {', '.join(['%s'] * len(COLUNAS_TRANSACAO))})",
                    [(usuario_id, extrato_id, *(t[c] for c in COLUNAS_TRANSACAO)) for t in gravar])
        return Gravacao(extrato_id, len(gravar), repetidas)

    def lista_extratos(self, usuario_id: UUID) -> list[dict[str, Any]]:
        return self._todas(
            "select id, nome_arquivo, banco, parser, periodo_inicio, periodo_fim, linhas_gravadas, enviado_em "
            "from public.extratos where usuario_id = %s order by enviado_em desc", usuario_id)

    def apaga_extrato(self, usuario_id: UUID, extrato_id: UUID) -> bool:
        """Apaga o extrato e as transações dele (cascata). False se não for do usuário."""
        cur = self.con.execute("delete from public.extratos where id = %s and usuario_id = %s",
                               (extrato_id, usuario_id))
        return cur.rowcount > 0

    def transacoes(self, usuario_id: UUID) -> list[dict[str, Any]]:
        return self._todas(
            "select data, historico, contraparte, valor, tipo, meio, banco, categoria from public.transacoes "
            "where usuario_id = %s order by data, id", usuario_id)

    # --- conversas do assistente ---

    def lista_conversas(self, usuario_id: UUID) -> list[dict[str, Any]]:
        return self._todas(
            "select id, titulo, criada_em, atualizada_em from public.conversas "
            "where usuario_id = %s order by atualizada_em desc", usuario_id)

    def cria_conversa(self, usuario_id: UUID, titulo: str) -> UUID:
        return self._uma("insert into public.conversas (usuario_id, titulo) values (%s, %s) returning id",
                         usuario_id, titulo)["id"]

    def conversa_e_do_usuario(self, usuario_id: UUID, conversa_id: UUID) -> bool:
        return self._uma("select 1 from public.conversas where id = %s and usuario_id = %s",
                         conversa_id, usuario_id) is not None

    def apaga_conversa(self, usuario_id: UUID, conversa_id: UUID) -> bool:
        cur = self.con.execute("delete from public.conversas where id = %s and usuario_id = %s",
                               (conversa_id, usuario_id))
        return cur.rowcount > 0

    def mensagens(self, conversa_id: UUID) -> list[dict[str, Any]]:
        return self._todas(
            "select id, papel, texto, grafico, criada_em from public.mensagens "
            "where conversa_id = %s order by criada_em, id", conversa_id)

    def grava_mensagem(self, conversa_id: UUID, papel: str, texto: str,
                       grafico: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._uma(
            "insert into public.mensagens (conversa_id, papel, texto, grafico) values (%s, %s, %s, %s) "
            "returning id, papel, texto, grafico, criada_em",
            conversa_id, papel, texto, json.dumps(grafico, default=_json) if grafico else None)


def _json(valor: Any) -> Any:
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    raise TypeError(type(valor))
