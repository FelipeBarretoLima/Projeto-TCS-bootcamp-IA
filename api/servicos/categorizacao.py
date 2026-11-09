"""Categoria de cada transação: regras fixas, mapa de estabelecimentos e, por último, o classificador.

Ordem (a primeira que achar vence):
    1. regra fixa (`ml.classes.por_regra`)         -> origem "regra"
    2. mapa de estabelecimentos pelo nome-base      -> origem "mapa"
    3. classificador treinado (`ml/modelos/*.pkl`)  -> origem "modelo"
Os passos 1 e 2 são a mesma lógica de `ml.rotular.categoria`. Sem o .pkl, o passo 3 é pulado e a
transação fica sem categoria, como antes.
"""

import logging
from pathlib import Path

import joblib
import pandas as pd

from extrato.estabelecimentos import nome_base
from extrato.modelos import COLUNAS, Meio, Tipo
from ml.classes import Categoria, por_regra
from ml.rotular import carrega_mapa

from .. import config
from ..esquemas import ResultadoUpload, Transacao

log = logging.getLogger(__name__)

# caminho -> (data de modificação, modelo): recarrega sozinho se o .pkl for treinado de novo
_cache_modelo: dict[Path, tuple[float, object]] = {}


class MapaInvalido(Exception):
    """O mapa de estabelecimentos tem classe inválida (a mensagem só diz arquivo e linha)."""


def carrega_modelo(caminho: Path):
    """O classificador do .pkl, ou None se ele não existir ou não carregar."""
    try:
        modificado = caminho.stat().st_mtime
    except FileNotFoundError:
        return None
    em_cache = _cache_modelo.get(caminho)
    if em_cache is not None and em_cache[0] == modificado:
        return em_cache[1]
    try:
        modelo = joblib.load(caminho)
    except Exception:  # versão diferente do scikit-learn, arquivo corrompido...
        log.exception("não foi possível carregar o classificador %s; seguindo sem ele", caminho)
        return None
    _cache_modelo[caminho] = (modificado, modelo)
    return modelo


def _por_regra_ou_mapa(t: Transacao, mapa: dict[str, Categoria]) -> Transacao:
    regra = por_regra(Meio(t.meio), Tipo(t.tipo), t.historico, t.contraparte)
    if regra is not None:
        return t.model_copy(update={"categoria": regra.value, "origem_categoria": "regra"})
    do_mapa = mapa.get(nome_base(t.contraparte))
    if do_mapa is not None:
        return t.model_copy(update={"categoria": do_mapa.value, "origem_categoria": "mapa"})
    return t


def _pelo_modelo(transacoes: list[Transacao], modelo) -> list[Transacao]:
    """Preenche, com o classificador, as transações que regra e mapa não resolveram."""
    pendentes = [i for i, t in enumerate(transacoes) if t.categoria is None]
    if not pendentes:
        return transacoes
    # o .pkl recebe as colunas do CSV do parser; id_usuario e data são ignorados pelo modelo
    linhas = []
    for i in pendentes:
        t = transacoes[i]
        linha = t.model_dump(include=set(COLUNAS) - {"id_usuario"})
        linha.update(id_usuario="", data=t.data.isoformat(), valor=float(t.valor))
        linhas.append(linha)
    previstas = modelo.predict(pd.DataFrame(linhas, columns=list(COLUNAS)))
    resultado = list(transacoes)
    for i, categoria in zip(pendentes, previstas):
        resultado[i] = transacoes[i].model_copy(
            update={"categoria": str(categoria), "origem_categoria": "modelo"}
        )
    return resultado


def categoriza(resultado: ResultadoUpload) -> ResultadoUpload:
    try:
        mapa = carrega_mapa(config.DIR_PRIVADO)
    except ValueError as exc:
        raise MapaInvalido(str(exc)) from None
    transacoes = [_por_regra_ou_mapa(t, mapa) for t in resultado.transacoes]
    modelo = carrega_modelo(config.CAMINHO_MODELO)
    if modelo is not None:
        transacoes = _pelo_modelo(transacoes, modelo)
    return resultado.model_copy(update={
        "transacoes": transacoes,
        "sem_categoria": sum(t.categoria is None for t in transacoes),
    })
