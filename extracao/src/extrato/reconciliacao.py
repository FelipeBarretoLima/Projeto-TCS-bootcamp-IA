"""Confere as transações extraídas contra os totais declarados no documento."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import Decimal

from .parsers.base import ErroExtracao, ResultadoExtracao


class ReconciliacaoFalhou(ErroExtracao):
    def __init__(self, divergentes: int, total: int, motivo: str = "soma não bate com o total declarado"):
        super().__init__(f"{motivo}: {divergentes} de {total} segmento(s)")
        self.divergentes = divergentes
        self.total = total


@dataclass(frozen=True)
class StatusReconciliacao:
    segmentos: int
    divergentes: int

    @property
    def ok(self) -> bool:
        return self.segmentos > 0 and self.divergentes == 0


def confere(resultado: ResultadoExtracao) -> StatusReconciliacao:
    """Calcula o status sem lançar exceção."""
    soma: dict[int, Decimal] = defaultdict(Decimal)
    for t in resultado.transacoes:
        for idx in (t.segmento if isinstance(t.segmento, tuple) else (t.segmento,)):
            soma[idx] += t.valor
    n = len(resultado.segmentos)
    orfas = sum(1 for idx in soma if not 0 <= idx < n)
    divergentes = orfas + sum(
        1 for i, s in enumerate(resultado.segmentos) if s.abertura + soma[i] != s.fechamento
    )
    return StatusReconciliacao(segmentos=n, divergentes=divergentes)


def _indices(t) -> tuple[int, ...]:
    return t.segmento if isinstance(t.segmento, tuple) else (t.segmento,)


def separa_documentos_divergentes(resultado: ResultadoExtracao) -> tuple[ResultadoExtracao, list[str]]:
    """Para arquivos com vários documentos independentes (REJEITA_POR_DOCUMENTO).

    Devolve (resultado só com os documentos que fecham, documentos rejeitados). Exige que todo
    segmento tenha `documento` e que nenhum lançamento misture documentos.
    """
    n = len(resultado.segmentos)
    if not n or any(not s.documento for s in resultado.segmentos):
        raise ReconciliacaoFalhou(0, n, "segmento sem documento")
    soma: dict[int, Decimal] = defaultdict(Decimal)
    for t in resultado.transacoes:
        idx = _indices(t)
        if any(not 0 <= i < n for i in idx) or len({resultado.segmentos[i].documento for i in idx}) > 1:
            raise ReconciliacaoFalhou(1, n, "lançamento fora de segmento ou em dois documentos")
        for i in idx:
            soma[i] += t.valor
    ruins = sorted({s.documento for i, s in enumerate(resultado.segmentos) if s.abertura + soma[i] != s.fechamento})
    if not ruins:
        return resultado, []
    fica = lambda t: not any(resultado.segmentos[i].documento in ruins for i in _indices(t))
    mapa = {i: j for j, i in enumerate(i for i, s in enumerate(resultado.segmentos) if s.documento not in ruins)}
    segmentos = [s for s in resultado.segmentos if s.documento not in ruins]
    transacoes = []
    for t in resultado.transacoes:
        if fica(t):
            transacoes.append(replace(t, segmento=tuple(mapa[i] for i in _indices(t))))
    return replace(resultado, transacoes=transacoes, segmentos=segmentos), ruins


def reconcilia(resultado: ResultadoExtracao) -> StatusReconciliacao:
    """Como `confere`, mas rejeita o arquivo se algo não bater."""
    if not resultado.segmentos:
        raise ReconciliacaoFalhou(0, 0, "documento sem totais declarados")
    status = confere(resultado)
    if not status.ok:
        raise ReconciliacaoFalhou(status.divergentes, status.segmentos)
    return status
