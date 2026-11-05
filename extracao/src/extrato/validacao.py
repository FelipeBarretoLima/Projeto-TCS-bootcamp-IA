"""Última barreira antes do disco: nenhum padrão de dado pessoal passa para o CSV."""

from __future__ import annotations

import csv
import os
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

from . import padroes
from .modelos import COLUNAS, LinhaSaida
from .parsers.base import ErroExtracao


class VazamentoDetectado(ErroExtracao):
    def __init__(self, contagem: Counter[str]):
        resumo = ", ".join(f"{tipo}={n}" for tipo, n in sorted(contagem.items()))
        super().__init__(f"gravação bloqueada: possível dado pessoal no CSV ({resumo})")
        self.contagem = contagem


def verifica(linhas: Iterable[LinhaSaida], nomes: re.Pattern[str] | None) -> Counter[str]:
    """Conta, por tipo, quantas linhas têm algum padrão proibido nos campos de texto."""
    contagem: Counter[str] = Counter()
    for linha in linhas:
        achados: set[str] = set()
        for campo in (linha.historico, linha.contraparte):
            achados.update(padroes.encontra(campo, nomes))
        contagem.update(achados)
    return contagem


def grava_csv(
    linhas: Sequence[LinhaSaida], caminho: Path, nomes_titulares: Sequence[str]
) -> None:
    """Valida tudo e só então grava (UTF-8 sem BOM, vírgula, '\\n').

    Escreve num arquivo temporário e renomeia no fim: se algo falhar, o CSV
    anterior (se houver) continua intacto e nada parcial fica no disco.
    """
    nomes = padroes.regex_de_nomes(list(nomes_titulares))
    contagem = verifica(linhas, nomes)
    if contagem:
        raise VazamentoDetectado(contagem)

    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(caminho.name + ".tmp")
    try:
        with open(temporario, "w", encoding="utf-8", newline="") as f:
            escritor = csv.writer(f, lineterminator="\n")
            escritor.writerow(COLUNAS)
            escritor.writerows(linha.como_linha_csv() for linha in linhas)
        os.replace(temporario, caminho)
    finally:
        temporario.unlink(missing_ok=True)
