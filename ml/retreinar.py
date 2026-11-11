"""Retreino com as correções de categoria feitas pelos usuários (sem banco: recebe tudo pronto).

Treino = CSV rotulado base (regras + mapa, `python -m ml.rotular`) + correções dos usuários:
  - cada correção pesa PESO_CORRECAO exemplos (uma só já muda o modelo);
  - a correção substitui o rótulo automático do mesmo estabelecimento no CSV base (nome-base da
    contraparte), menos PESSOA_FISICA e contraparte vazia: corrigir um PIX para um amigo não
    muda todos os PIX para pessoas;
  - correções que discordam no mesmo estabelecimento: vale a mais recente.
As correções chegam só com os campos anonimizados do contrato do parser (nunca o texto original).

Quem busca as correções no banco, troca o .pkl e registra o histórico é api/servicos/retreino.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from extrato.estabelecimentos import nome_base
from extrato.modelos import COLUNAS, PESSOA_FISICA

from .treinar import ALVO, monta_modelo

PESO_CORRECAO = 5
CORRECOES_PARA_RETREINAR = 15
_GENERICAS = ("", PESSOA_FISICA)


@dataclass(frozen=True)
class ResultadoRetreino:
    modelo: object
    correcoes: int
    linhas_treino: int
    acerto_correcoes_antes: float | None  # % das correções que o modelo anterior já acertava
    acerto_correcoes_depois: float        # % das correções que o modelo novo acerta
    acerto_base_depois: float             # % do CSV base (já com os rótulos substituídos)


def _pct(certos: np.ndarray) -> float:
    return round(100 * float(np.mean(certos)), 2) if len(certos) else 0.0


def monta_treino(base: pd.DataFrame, correcoes: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """CSV base com os rótulos substituídos + as correções, e o peso de cada linha.

    `correcoes`: colunas do parser + `categoria` + `corrigida_em` (para decidir a mais recente).
    """
    base = base.copy()
    corr = correcoes.sort_values("corrigida_em") if "corrigida_em" in correcoes else correcoes
    chave_corr = corr["contraparte"].map(nome_base)
    especificas = ~chave_corr.isin(_GENERICAS)
    # o mesmo estabelecimento corrigido mais de uma vez: a última correção vence
    por_loja = dict(zip(chave_corr[especificas], corr.loc[especificas, ALVO]))
    if por_loja:
        chave_base = base["contraparte"].map(nome_base)
        trocar = chave_base.isin(list(por_loja))
        base.loc[trocar, ALVO] = chave_base[trocar].map(por_loja)
    treino = pd.concat([base[[*COLUNAS, ALVO]], corr[[*COLUNAS, ALVO]]], ignore_index=True)
    pesos = np.concatenate([np.ones(len(base)), np.full(len(corr), PESO_CORRECAO, dtype=float)])
    return treino, pesos


def retreina(base: pd.DataFrame, correcoes: pd.DataFrame, modelo_atual=None) -> ResultadoRetreino:
    """Treina o modelo novo. `modelo_atual` (opcional) só serve para medir o "antes"."""
    if base.empty:
        raise ValueError("CSV base de treino vazio")
    if (base[ALVO] == "").any() or (correcoes[ALVO] == "").any():
        raise ValueError("há linhas sem categoria no treino")
    treino, pesos = monta_treino(base, correcoes)
    X, y = treino.drop(columns=[ALVO]), treino[ALVO]
    modelo = monta_modelo().fit(X, y, clf__sample_weight=pesos)

    Xc, yc = correcoes[list(COLUNAS)], correcoes[ALVO].to_numpy()
    antes = _pct(modelo_atual.predict(Xc) == yc) if modelo_atual is not None and len(correcoes) else None
    n_base = len(treino) - len(correcoes)
    return ResultadoRetreino(
        modelo=modelo,
        correcoes=len(correcoes),
        linhas_treino=len(treino),
        acerto_correcoes_antes=antes,
        acerto_correcoes_depois=_pct(modelo.predict(Xc) == yc) if len(correcoes) else 0.0,
        acerto_base_depois=_pct(modelo.predict(X.iloc[:n_base]) == y.iloc[:n_base].to_numpy()),
    )


def le_base(caminho: Path) -> pd.DataFrame:
    df = pd.read_csv(caminho, keep_default_na=False)
    if ALVO not in df.columns:
        raise ValueError(f"o CSV base não tem a coluna {ALVO!r} (gere com python -m ml.rotular)")
    return df
