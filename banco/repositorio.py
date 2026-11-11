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

from .deduplicacao import separa_novas_com_ids

COLUNAS_TRANSACAO = ("data", "historico", "contraparte", "valor", "tipo", "meio", "banco",
                     "categoria", "origem_categoria")
# texto original cifrado pela API (api/cifra.py); opcional em cada transação
COLUNA_ORIGINAL = "original_cifrado"


class ExtratoRepetido(Exception):
    """O mesmo arquivo (mesmo hash) já foi enviado por este usuário."""


class ConversaApagada(Exception):
    """A conversa foi apagada enquanto a resposta era gerada."""


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

    def muda_nome(self, usuario_id: UUID, nome: str) -> None:
        self.con.execute("update public.usuarios set nome = %s where id = %s", (nome, usuario_id))

    def apaga_conta(self, usuario_id: UUID) -> None:
        """Apaga o login no Supabase Auth; perfil, extratos, transações e conversas vão em cascata."""
        self.con.execute("delete from auth.users where id = %s", (usuario_id,))

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
                "select id, banco, data, valor, tipo, meio, historico, contraparte from public.transacoes "
                "where usuario_id = %s and banco = any(%s) and data between %s and %s order by id",
                usuario_id, sorted({t["banco"] for t in transacoes}), min(datas), max(datas))
        gravar, ids_repetidas = separa_novas_com_ids(existentes, transacoes)
        bancos = Counter(t["banco"] for t in transacoes)
        banco = bancos.most_common(1)[0][0] if bancos else ""
        try:
            extrato_id = self._uma(
                "insert into public.extratos (usuario_id, nome_arquivo, hash_arquivo, banco, parser, "
                "periodo_inicio, periodo_fim, linhas_gravadas) values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
                usuario_id, nome_arquivo, hash_arquivo, banco, parser, periodo_inicio, periodo_fim, len(gravar))["id"]
        except psycopg.errors.UniqueViolation:
            # o mesmo arquivo chegou duas vezes ao mesmo tempo (ex.: duas abas): o outro envio ganhou
            raise ExtratoRepetido from None
        if gravar:
            with self.con.cursor() as cur:
                colunas = (*COLUNAS_TRANSACAO, COLUNA_ORIGINAL)
                cur.executemany(
                    f"insert into public.transacoes (usuario_id, extrato_id, {', '.join(colunas)}) "
                    f"values (%s, %s, {', '.join(['%s'] * len(colunas))})",
                    [(usuario_id, extrato_id, *(t[c] for c in COLUNAS_TRANSACAO), t.get(COLUNA_ORIGINAL))
                     for t in gravar])
        # vínculos: as gravadas agora e as repetidas (que já estavam no banco vindas de outro extrato)
        self.con.execute(
            "insert into public.extrato_transacoes (extrato_id, transacao_id) "
            "select %s, id from public.transacoes where extrato_id = %s",
            (extrato_id, extrato_id))
        if ids_repetidas:
            self.con.execute(
                "insert into public.extrato_transacoes (extrato_id, transacao_id) "
                "select %s, unnest(%s::bigint[]) on conflict do nothing",
                (extrato_id, ids_repetidas))
        return Gravacao(extrato_id, len(gravar), len(ids_repetidas))

    def lista_extratos(self, usuario_id: UUID) -> list[dict[str, Any]]:
        return self._todas(
            "select id, nome_arquivo, banco, parser, periodo_inicio, periodo_fim, linhas_gravadas, enviado_em "
            "from public.extratos where usuario_id = %s order by enviado_em desc", usuario_id)

    def apaga_extrato(self, usuario_id: UUID, extrato_id: UUID) -> bool:
        """Apaga o extrato e as transações que só ele trouxe. False se não for do usuário.

        Uma transação que outro extrato também trouxe (períodos sobrepostos) não é apagada: passa
        para esse outro extrato, que continua importado.
        """
        if not self._uma("select 1 from public.extratos where id = %s and usuario_id = %s",
                         extrato_id, usuario_id):
            return False
        herdeiros = self._todas(
            "update public.transacoes t set extrato_id = o.extrato_id "
            "from (select distinct on (et.transacao_id) et.transacao_id, et.extrato_id "
            "      from public.extrato_transacoes et "
            "      join public.extratos e on e.id = et.extrato_id and e.usuario_id = %s "
            "      where et.extrato_id <> %s and et.transacao_id in "
            "            (select id from public.transacoes where extrato_id = %s) "
            "      order by et.transacao_id, e.enviado_em) o "
            "where t.id = o.transacao_id returning t.extrato_id",
            usuario_id, extrato_id, extrato_id)
        if herdeiros:
            self.con.execute(
                "update public.extratos e set linhas_gravadas = "
                "(select count(*) from public.transacoes t where t.extrato_id = e.id) where e.id = any(%s)",
                (sorted({h["extrato_id"] for h in herdeiros}),))
        cur = self.con.execute("delete from public.extratos where id = %s and usuario_id = %s",
                               (extrato_id, usuario_id))
        return cur.rowcount > 0

    def transacoes(self, usuario_id: UUID) -> list[dict[str, Any]]:
        return self._todas(
            "select data, historico, contraparte, valor, tipo, meio, banco, categoria from public.transacoes "
            "where usuario_id = %s order by data, id", usuario_id)

    def periodo_transacoes(self, usuario_id: UUID) -> tuple[date | None, date | None]:
        """Data da primeira e da última transação do usuário (None, None se não houver)."""
        linha = self._uma("select min(data) as primeira, max(data) as ultima from public.transacoes "
                          "where usuario_id = %s", usuario_id)
        return linha["primeira"], linha["ultima"]

    def busca_transacoes(self, usuario_id: UUID, *, inicio: date | None = None, fim: date | None = None,
                         categoria: str | None = None, sem_categoria: bool = False) -> list[dict[str, Any]]:
        """Transações do usuário para a aba Extrato, da mais recente para a mais antiga.

        Filtros opcionais: período (inclusivo) e uma categoria, ou só as sem categoria.
        Inclui o original cifrado (só a aba Extrato decifra; `transacoes()`, do chat, não o lê).
        """
        condicoes, args = ["usuario_id = %s"], [usuario_id]
        if inicio is not None:
            condicoes.append("data >= %s")
            args.append(inicio)
        if fim is not None:
            condicoes.append("data <= %s")
            args.append(fim)
        if sem_categoria:
            condicoes.append("categoria is null")
        elif categoria is not None:
            condicoes.append("categoria = %s")
            args.append(categoria)
        return self._todas(
            "select id, data, historico, contraparte, valor, tipo, meio, banco, categoria, original_cifrado "
            f"from public.transacoes where {' and '.join(condicoes)} order by data desc, id desc", *args)

    def muda_categoria(self, usuario_id: UUID, transacao_id: int, categoria: str | None) -> bool:
        """Correção feita pelo usuário (origem "usuario"); None = sem categoria. False se não for dele."""
        cur = self.con.execute(
            "update public.transacoes set categoria = %s, "
            "origem_categoria = case when %s::text is null then null else 'usuario' end "
            "where id = %s and usuario_id = %s",
            (categoria, categoria, transacao_id, usuario_id))
        return cur.rowcount > 0

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

    def renomeia_conversa(self, usuario_id: UUID, conversa_id: UUID, titulo: str) -> bool:
        cur = self.con.execute("update public.conversas set titulo = %s where id = %s and usuario_id = %s",
                               (titulo, conversa_id, usuario_id))
        return cur.rowcount > 0

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
        try:
            return self._uma(
                "insert into public.mensagens (conversa_id, papel, texto, grafico) values (%s, %s, %s, %s) "
                "returning id, papel, texto, grafico, criada_em",
                conversa_id, papel, texto, json.dumps(grafico, default=_json) if grafico else None)
        except psycopg.errors.ForeignKeyViolation:
            raise ConversaApagada from None


def _json(valor: Any) -> Any:
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    raise TypeError(type(valor))
