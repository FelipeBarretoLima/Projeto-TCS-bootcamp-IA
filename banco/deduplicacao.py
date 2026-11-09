"""Não contar duas vezes a mesma transação quando dois extratos se sobrepõem.

Regra (combinada com o grupo): dentro do mesmo usuário e do mesmo banco, cada transação é
identificada por (banco, data, valor, tipo, meio, histórico, contraparte). A comparação é por CONTAGEM:
se o banco já tem 2 linhas iguais e o extrato novo traz 3, entra só 1 (a que faltava).

- Mesma compra em dois extratos que se sobrepõem -> entra uma vez.
- Duas compras iguais de verdade no mesmo extrato (duas corridas de R$ 8,94 no mesmo dia) -> entram as duas.
- A mesma compra em bancos diferentes -> entram as duas (a busca é feita só no mesmo banco).
Nada já gravado é apagado ou alterado.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from typing import Any

Chave = tuple[str, date, Decimal, str, str, str, str]


def chave(t: Mapping[str, Any]) -> Chave:
    return (t["banco"], t["data"], Decimal(t["valor"]).quantize(Decimal("0.01")), t["tipo"], t["meio"],
            t["historico"], t["contraparte"] or "")


def separa_novas(existentes: Iterable[Mapping[str, Any]], novas: list[Mapping[str, Any]]):
    """Devolve (as que devem ser gravadas, quantas eram repetidas), na ordem do extrato."""
    restam = Counter(chave(t) for t in existentes)
    gravar, repetidas = [], 0
    for t in novas:
        k = chave(t)
        if restam[k] > 0:
            restam[k] -= 1
            repetidas += 1
        else:
            gravar.append(t)
    return gravar, repetidas
