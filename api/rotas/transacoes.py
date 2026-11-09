"""Transações salvas na conta do usuário (aba Extrato), com filtro de período e categoria."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from banco.repositorio import Banco
from ml.classes import Categoria

from ..autenticacao import Usuario, usuario_atual
from ..dependencias import banco
from ..esquemas import PeriodoTransacoes, TransacaoSalva

router = APIRouter(tags=["transacoes"])

SEM_CATEGORIA = "sem_categoria"
MESES_PADRAO = 6


def inicio_da_janela(ultima: date, meses: int = MESES_PADRAO) -> date:
    """1º dia do mês que abre a janela de N meses terminada no mês de `ultima`.

    Mesma regra do dashboard (agente/consultas.py): a janela termina no mês da transação mais
    recente, não no mês de hoje. Ex.: última em 15/03/2024, 6 meses -> 01/10/2023.
    """
    indice = ultima.year * 12 + (ultima.month - 1) - (meses - 1)
    return date(indice // 12, indice % 12 + 1, 1)


@router.get("/transacoes/periodo")
def periodo(
    usuario: Annotated[Usuario, Depends(usuario_atual)], db: Annotated[Banco, Depends(banco)]
) -> PeriodoTransacoes:
    primeira, ultima = db.periodo_transacoes(usuario.id)
    if ultima is None:
        return PeriodoTransacoes(primeira=None, ultima=None, padrao_inicio=None, padrao_fim=None)
    return PeriodoTransacoes(primeira=primeira, ultima=ultima,
                             padrao_inicio=max(primeira, inicio_da_janela(ultima)), padrao_fim=ultima)


@router.get("/transacoes")
def lista_transacoes(
    usuario: Annotated[Usuario, Depends(usuario_atual)],
    db: Annotated[Banco, Depends(banco)],
    inicio: Annotated[date | None, Query(description="Data inicial (inclusiva), AAAA-MM-DD")] = None,
    fim: Annotated[date | None, Query(description="Data final (inclusiva), AAAA-MM-DD")] = None,
    categoria: Annotated[str | None, Query(description="Uma das categorias ou 'sem_categoria'")] = None,
) -> list[TransacaoSalva]:
    if inicio and fim and inicio > fim:
        raise HTTPException(400, "a data inicial deve ser anterior ou igual à data final")
    validas = {c.value for c in Categoria}
    if categoria is not None and categoria != SEM_CATEGORIA and categoria not in validas:
        raise HTTPException(400, "categoria inválida")
    linhas = db.busca_transacoes(
        usuario.id,
        inicio=inicio,
        fim=fim,
        categoria=categoria if categoria in validas else None,
        sem_categoria=categoria == SEM_CATEGORIA,
    )
    return [TransacaoSalva(**t) for t in linhas]
