"""Conta Nubank: CSV exportado pelo app (Data,Valor,Identificador,Descrição).

O arquivo não traz saldo nem total: é aceito com reconciliação "sem_totais".
Conferências que dá para fazer: cabeçalho exato, formato de data/valor/identificador
e sinal coerente com o tipo do lançamento.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .base import LayoutInesperado, Parser, ResultadoExtracao, TransacaoBruta, primeira_linha
from . import nubank_comum as nu

CABECALHO = "Data,Valor,Identificador,Descrição"
_VALOR = re.compile(r"^-?\d+\.\d{2}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class NubankContaCsv(Parser):
    nome = "nubank_conta_csv"
    banco = "nubank"
    produto = "conta"
    MEIOS = nu.MEIOS
    SEM_TOTAIS = True

    @classmethod
    def detecta(cls, caminho: Path) -> bool:
        return caminho.suffix.lower() == ".csv" and primeira_linha(caminho) == CABECALHO

    def extrai(self, caminho: Path) -> ResultadoExtracao:
        transacoes = []
        with open(caminho, encoding="utf-8-sig", newline="") as f:
            leitor = csv.reader(f)
            if next(leitor) != CABECALHO.split(","):
                raise LayoutInesperado(self.nome, "cabecalho")
            for n, linha in enumerate(leitor, start=2):
                transacoes.append(self._linha(linha, n))
        if not transacoes:
            raise LayoutInesperado(self.nome, "arquivo_sem_lancamentos")
        return ResultadoExtracao(self.banco, self.produto, transacoes, segmentos=[])

    def _linha(self, linha: list[str], n: int) -> TransacaoBruta:
        # n = nº da linha no arquivo, usado como "página" nas mensagens de erro
        if len(linha) != 4:
            raise LayoutInesperado(self.nome, "numero_de_colunas", n)
        data_txt, valor_txt, ident, descricao = linha
        try:
            data = datetime.strptime(data_txt, "%d/%m/%Y").date()
        except ValueError:
            raise LayoutInesperado(self.nome, "data", n) from None
        if not _VALOR.match(valor_txt):
            raise LayoutInesperado(self.nome, "valor", n)
        if not _UUID.match(ident):
            raise LayoutInesperado(self.nome, "identificador", n)
        valor = Decimal(valor_txt)

        # no CSV o tipo vem separado por " - " do resto
        tipo, resto = nu.separa_tipo(descricao)
        if tipo in nu.TIPOS:
            if resto and not resto.startswith("- "):
                raise LayoutInesperado(self.nome, "separador_do_tipo", n)
            if (valor > 0) != (nu.TIPOS[tipo].sinal > 0):
                raise LayoutInesperado(self.nome, "sinal_incoerente_com_tipo", n)
            try:
                nome, doc = nu.contraparte(tipo, resto)
            except nu.ComplementoInvalido as exc:
                raise LayoutInesperado(self.nome, str(exc), n) from None
        else:
            tipo, nome, doc = descricao.split(" - ", 1)[0], "", ""
        return TransacaoBruta(data, tipo, valor, 0, nome, doc, pagina=n)
