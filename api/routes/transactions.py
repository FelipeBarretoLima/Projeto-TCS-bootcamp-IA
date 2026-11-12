"""Transações salvas na conta do usuário (aba Extrato), com filtro de período e categoria."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from database.repository import Banco
from ml.classes import Category

from .. import cipher
from ..auth import Usuario, usuario_atual
from ..dependencies import banco
from ..schemas import NovaCategoria, PeriodoTransacoes, TransacaoSalva
from ..services import retraining

router = APIRouter(tags=["transacoes"])

SEM_CATEGORIA = "sem_categoria"
MESES_PADRAO = 6
# o id é bigint no banco: fora deste intervalo o Postgres dava erro e a rota respondia 500
ID_MAXIMO = 2**63 - 1


def inicio_da_janela(ultima: date, meses: int = MESES_PADRAO) -> date:
    """1º dia do mês que abre a janela de N meses terminada no mês de `ultima`.

    Mesma regra do dashboard (agent/queries.py): a janela termina no mês da transação mais
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
    validas = {c.value for c in Category}
    if categoria is not None and categoria != SEM_CATEGORIA and categoria not in validas:
        raise HTTPException(400, "categoria inválida")
    linhas = db.busca_transacoes(
        usuario.id,
        inicio=inicio,
        fim=fim,
        categoria=categoria if categoria in validas else None,
        sem_categoria=categoria == SEM_CATEGORIA,
    )
    try:
        return [_com_original(t) for t in linhas]
    except cipher.ChaveInvalida as exc:
        raise HTTPException(500, str(exc)) from None


def _com_original(linha: dict) -> TransacaoSalva:
    """Decifra o original só para devolver ao dono; o texto cifrado não sai da API."""
    original = cipher.decifra(linha.pop("original_cifrado", None)) or {}
    return TransacaoSalva(**linha, historico_original=original.get("historico") or None,
                          contraparte_original=original.get("contraparte") or None)


@router.patch("/transacoes/{transacao_id}", status_code=204)
def muda_categoria(
    transacao_id: Annotated[int, Path(ge=1, le=ID_MAXIMO)],
    nova: NovaCategoria,
    usuario: Annotated[Usuario, Depends(usuario_atual)],
    db: Annotated[Banco, Depends(banco)],
) -> Response:
    """O usuário corrige a categoria (vale para o dashboard e o assistente). None = sem categoria.

    A correção também vira exemplo de treino: a cada 15 novas, o modelo é retreinado em segundo
    plano (api/services/retraining.py).
    """
    if nova.categoria is not None and nova.categoria not in {c.value for c in Category}:
        raise HTTPException(400, "categoria inválida")
    if not db.muda_categoria(usuario.id, transacao_id, nova.categoria):
        raise HTTPException(404, "transação não encontrada")
    # grava já: o retreino roda noutra conexão e precisa ver esta correção
    db.confirma()
    retraining.dispara_se_preciso(db)
    return Response(status_code=204)
