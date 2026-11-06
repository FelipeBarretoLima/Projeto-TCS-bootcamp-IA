"""Categoria de cada transação: regras fixas e mapa de estabelecimentos do módulo `ml`.

Mesma lógica de `ml.rotular.categoria` (regra primeiro; senão, o mapa pelo nome-base), mas
guardando de onde veio a categoria. Quando o classificador existir, ele entra aqui para as
transações que ficarem sem categoria.
"""

from extrato.estabelecimentos import nome_base
from extrato.modelos import Meio, Tipo
from ml.classes import Categoria, por_regra
from ml.rotular import carrega_mapa

from .. import config
from ..esquemas import ResultadoUpload, Transacao


class MapaInvalido(Exception):
    """O mapa de estabelecimentos tem classe inválida (a mensagem só diz arquivo e linha)."""


def _categoriza(t: Transacao, mapa: dict[str, Categoria]) -> Transacao:
    regra = por_regra(Meio(t.meio), Tipo(t.tipo), t.historico, t.contraparte)
    if regra is not None:
        return t.model_copy(update={"categoria": regra.value, "origem_categoria": "regra"})
    do_mapa = mapa.get(nome_base(t.contraparte))
    if do_mapa is not None:
        return t.model_copy(update={"categoria": do_mapa.value, "origem_categoria": "mapa"})
    return t


def categoriza(resultado: ResultadoUpload) -> ResultadoUpload:
    try:
        mapa = carrega_mapa(config.DIR_PRIVADO)
    except ValueError as exc:
        raise MapaInvalido(str(exc)) from None
    transacoes = [_categoriza(t, mapa) for t in resultado.transacoes]
    return resultado.model_copy(update={
        "transacoes": transacoes,
        "sem_categoria": sum(t.categoria is None for t in transacoes),
    })
