"""Categoria de cada transação: entradas por regra, saídas pelo classificador (ML).

    1. entrada (dinheiro recebido)  -> "receitas"                  origem "regra"
    2. saída                         -> classificador ml/modelos/*.pkl  origem "modelo"

As regras fixas e o mapa de estabelecimentos (ml.classes.por_regra, data/privado) não entram aqui:
eles só geram os rótulos do treino (python -m ml.rotular). O modelo aprendeu o que eles faziam.
Medido no CSV rotulado, só nas saídas: ~99% de acerto em estabelecimento já visto, 100% em PIX
para pessoa/tarifa/fatura e ~81% em estabelecimento nunca visto (validação cruzada por loja).

Sem o .pkl, as saídas ficam sem categoria.
"""

import logging
from pathlib import Path

import joblib
import pandas as pd

from extrato.modelos import COLUNAS
from ml.classes import Categoria

from .. import config
from ..esquemas import ResultadoUpload, Transacao

log = logging.getLogger(__name__)

# caminho -> (data de modificação, modelo): recarrega sozinho se o .pkl for treinado de novo
_cache_modelo: dict[Path, tuple[float, object]] = {}


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


def _entrada_e_receita(t: Transacao) -> Transacao:
    if t.tipo == "entrada":
        return t.model_copy(update={"categoria": Categoria.RECEITAS.value, "origem_categoria": "regra"})
    return t


def _pelo_modelo(transacoes: list[Transacao], modelo) -> list[Transacao]:
    """Classifica com o modelo as transações ainda sem categoria (as saídas)."""
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
    transacoes = [_entrada_e_receita(t) for t in resultado.transacoes]
    modelo = carrega_modelo(config.CAMINHO_MODELO)
    if modelo is not None:
        transacoes = _pelo_modelo(transacoes, modelo)
    else:
        log.warning("classificador ausente (%s): as saídas ficam sem categoria", config.CAMINHO_MODELO)
    return resultado.model_copy(update={
        "transacoes": transacoes,
        "sem_categoria": sum(t.categoria is None for t in transacoes),
    })
