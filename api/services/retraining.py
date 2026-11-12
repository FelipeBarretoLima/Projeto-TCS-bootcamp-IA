"""Retreino automático: a cada 15 correções de categoria novas, o modelo é treinado de novo.

    python -m api.retrain     força um retreino agora (sem esperar as 15)

Fluxo (numa thread à parte, com conexão própria: o usuário não espera):
  1. registra o início em treinos_modelo ("rodando": outro retreino não começa junto);
  2. lê as correções de todos os usuários (só campos anonimizados) e o CSV base de treino;
  3. treina (ml/retrain.py: correção pesa 5 e substitui o rótulo automático da loja);
  4. troca o .pkl de uma vez (o anterior fica em svm_tfidf.anterior.pkl): a API carrega o novo
     sozinha na próxima importação (categorizacao.carrega_modelo olha a data do arquivo);
  5. registra o resultado (acertos antes/depois) ou o erro.
O modelo novo entra sempre (decisão do usuário em 2026-11-11); os acertos ficam só registrados.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import joblib
import pandas as pd

from database.connection import conexao
from database.repository import Banco
from statement.models import COLUMNS
from ml.retrain import CORRECTIONS_TO_RETRAIN, read_base, retrain

from .. import config
from .categorization import carrega_modelo

log = logging.getLogger(__name__)

_um_por_vez = threading.Lock()


@contextmanager
def _abre_banco() -> Iterator[Banco]:
    with conexao(config.DATABASE_URL) as con:
        yield Banco(con)


# trocado nos testes por um banco falso
abre_banco: Callable[[], AbstractContextManager[Banco]] = _abre_banco


def precisa_retreinar(db: Banco) -> bool:
    return db.correcoes_desde_ultimo_treino() >= CORRECTIONS_TO_RETRAIN and not db.treino_rodando()


def _como_tabela(linhas: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(linhas, columns=[*COLUMNS, "categoria", "corrigida_em"])
    df["id_usuario"] = ""
    df["data"] = df["data"].astype(str)
    df["valor"] = df["valor"].astype(float)
    return df


def _salva(modelo) -> None:
    """Grava ao lado e troca de uma vez: quem carrega o .pkl nunca pega um arquivo pela metade."""
    destino = config.CAMINHO_MODELO
    novo = destino.with_name(destino.stem + ".novo.pkl")
    joblib.dump(modelo, novo)
    if destino.exists():
        shutil.copy2(destino, destino.with_name(destino.stem + ".anterior.pkl"))
    os.replace(novo, destino)


def executa_retreino() -> dict[str, Any] | None:
    """Roda um retreino agora. None se outro já estiver rodando. Devolve o que foi registrado."""
    if not _um_por_vez.acquire(blocking=False):
        return None
    try:
        with abre_banco() as db:
            treino_id = db.inicia_treino_se_livre()  # atômico: outro processo pode estar retreinando
            if treino_id is None:
                return None
            correcoes = _como_tabela(db.correcoes_para_treino())
        try:
            r = retrain(read_base(config.CAMINHO_TREINO_BASE), correcoes, carrega_modelo(config.CAMINHO_MODELO))
            _salva(r.model)
            registro = dict(status="ok", correcoes=r.correcoes, linhas_treino=r.linhas_treino,
                            acerto_correcoes_antes=r.acerto_correcoes_antes,
                            acerto_correcoes_depois=r.acerto_correcoes_depois,
                            acerto_base_depois=r.acerto_base_depois)
        except (OSError, ValueError) as exc:  # CSV base ausente, sem categoria... (mensagens nossas)
            registro = dict(status="erro", correcoes=len(correcoes), mensagem=f"{type(exc).__name__}: {exc}")
        except Exception as exc:  # outra falha: só o tipo (a mensagem pode trazer valores dos dados)
            log.exception("retreino falhou")
            registro = dict(status="erro", correcoes=len(correcoes), mensagem=type(exc).__name__)
        with abre_banco() as db:
            db.conclui_treino(treino_id, **registro)
        log.info("retreino %s: %s", treino_id, registro)
        return registro
    finally:
        _um_por_vez.release()


def _em_segundo_plano(alvo: Callable[[], object]) -> None:
    threading.Thread(target=alvo, name="retreino", daemon=True).start()


# trocado nos testes para rodar na hora
inicia_em_segundo_plano: Callable[[Callable[[], object]], None] = _em_segundo_plano


def dispara_se_preciso(db: Banco) -> bool:
    """Chamado depois de gravar uma correção (já confirmada no banco). True se disparou."""
    try:
        if not precisa_retreinar(db):
            return False
    except Exception:  # o retreino nunca pode atrapalhar a correção do usuário
        log.exception("não foi possível verificar se precisa retreinar")
        return False
    inicia_em_segundo_plano(executa_retreino)
    return True
