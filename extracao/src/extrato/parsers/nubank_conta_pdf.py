"""Conta Nubank: extrato em PDF (um ou vários extratos mesclados no mesmo arquivo).

Layout de cada página:
    0  NOME DO TITULAR
    1  CPF •••.123.456-•• Agência 0001 Conta
    2  12345678-9
    3  01 DE JANEIRO DE 2026 a 31 DE JANEIRO DE 2026 VALORES EM R$
    …  corpo
    rodapé fixo ("Tem alguma dúvida?…", "Extrato gerado dia…")
Primeira página de cada extrato: resumo (saldo inicial, rendimento, entradas, saídas,
saldo final) e "Movimentações". Corpo: grupos "DD MMM AAAA Total de entradas|saídas ± X"
(a data some quando é o 2º grupo do mesmo dia) com lançamentos "Tipo complemento 1.234,56";
o complemento pode continuar nas linhas seguintes (sem valor no fim).

Reconciliação, cada lançamento em três segmentos:
    grupo do dia (0 -> ±total do grupo), total de entradas/saídas do extrato,
    saldo inicial + rendimento líquido + lançamentos == saldo final.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..normalizacao import valor_br
from . import nubank_comum as nu
from .base import LayoutInesperado, Parser, ResultadoExtracao, Segmento, TransacaoBruta, texto_pdf

_MESES = {m: i for i, m in enumerate("JAN FEV MAR ABR MAI JUN JUL AGO SET OUT NOV DEZ".split(), start=1)}
_MESES_EXTENSO = ("JANEIRO FEVEREIRO MARÇO ABRIL MAIO JUNHO JULHO AGOSTO SETEMBRO OUTUBRO NOVEMBRO DEZEMBRO").split()

_NUM = r"\d{1,3}(?:\.\d{3})*,\d{2}"
_CAB_CPF = re.compile(r"^CPF •••\.\d{3}\.\d{3}-•• Agência \d{4} Conta$")
_CAB_CONTA = re.compile(r"^\d+-\d$")
_MES_EXT = "(?:" + "|".join(_MESES_EXTENSO) + ")"
_CAB_PERIODO = re.compile(rf"^\d{{2}} DE {_MES_EXT} DE \d{{4}} a \d{{2}} DE {_MES_EXT} DE \d{{4}} VALORES EM R\$$")

_GRUPO = re.compile(rf"^(?:(?P<d>\d{{2}}) (?P<m>{'|'.join(_MESES)}) (?P<a>\d{{4}}) )?"
                    rf"Total de (?P<lado>entradas|saídas) (?P<sinal>[+-]) (?P<v>{_NUM})$")
# data sozinha no fim da página: o "Total de …" desse grupo vem no topo da página seguinte
_SO_DATA = re.compile(rf"^(?P<d>\d{{2}}) (?P<m>{'|'.join(_MESES)}) (?P<a>\d{{4}})$")
_LANCAMENTO = re.compile(rf"^(?P<texto>.+?) (?P<v>{_NUM})$")

_RESUMO = {
    "inicial": re.compile(rf"^Saldo inicial (?P<v>-?{_NUM})$"),
    "rendimento": re.compile(rf"^Rendimento líquido (?P<v>[+-]{_NUM})$"),
    "entradas": re.compile(rf"^(?:R\$ -?{_NUM} )?Total de entradas (?P<v>\+{_NUM})$"),
    "saidas": re.compile(rf"^Total de saídas (?P<v>-{_NUM})$"),
    "final": re.compile(rf"^Saldo final do período (?P<v>-?{_NUM})$"),
}
_RESUMO_FIXAS = {"Saldo final do período", "Movimentações"}
_RODAPE = ("Tem alguma dúvida?", "metropolitanas)", "Caso a solução fornecida",
           "disponíveis em nubank.com.br", "Extrato gerado dia ")
_AVISO_FINAL = "O saldo líquido"  # bloco de avisos legais no fim de cada extrato


@dataclass
class _Extrato:
    resumo: dict[str, Decimal] = field(default_factory=dict)
    idx_extrato: int = -1
    idx_entradas: int = -1
    idx_saidas: int = -1


class NubankContaPdf(Parser):
    nome = "nubank_conta_pdf"
    banco = "nubank"
    produto = "conta"
    MEIOS = nu.MEIOS

    @classmethod
    def detecta(cls, caminho: Path) -> bool:
        if caminho.suffix.lower() != ".pdf":
            return False
        paginas = texto_pdf(caminho, 1)
        if not paginas:
            return False
        linhas = paginas[0].splitlines()
        return (
            len(linhas) > 4
            and bool(_CAB_CPF.match(linhas[1]))
            and bool(_CAB_PERIODO.match(linhas[3]))
            and any(l.startswith("disponíveis em nubank.com.br") for l in linhas)
        )

    def extrai(self, caminho: Path) -> ResultadoExtracao:
        paginas = texto_pdf(caminho)
        segmentos: list[Segmento] = []
        transacoes: list[TransacaoBruta] = []
        titulares: set[str] = set()
        extrato: _Extrato | None = None
        data_grupo: date | None = None
        grupo: tuple[int, int] | None = None  # (índice do segmento, sinal)
        # lançamento em montagem: (página, data, sinal, segmentos, texto, valor)
        pendente: list | None = None

        def fecha_pendente() -> None:
            nonlocal pendente
            if pendente is not None:
                transacoes.append(self._monta(*pendente))
                pendente = None

        for num, texto in enumerate(paginas, start=1):
            linhas = texto.splitlines()
            if len(linhas) < 4 or not _CAB_CPF.match(linhas[1]) or not _CAB_CONTA.match(linhas[2]) \
                    or not _CAB_PERIODO.match(linhas[3]):
                raise LayoutInesperado(self.nome, "cabecalho", num)
            titulares.add(linhas[0].strip())
            corpo = linhas[4:]

            # página de resumo = início de um novo extrato
            if corpo and _RESUMO["inicial"].match(corpo[0]):
                fecha_pendente()
                extrato, corpo = self._le_resumo(corpo, segmentos, num)
                data_grupo, grupo = None, None
            if extrato is None:
                raise LayoutInesperado(self.nome, "extrato_sem_resumo", num)

            em_aviso = False
            for linha in corpo:
                if em_aviso or linha.startswith(_AVISO_FINAL):
                    em_aviso = True  # resto da página são avisos legais
                    continue
                if linha.startswith(_RODAPE):
                    continue
                if m := _GRUPO.match(linha):
                    fecha_pendente()
                    if m["d"]:
                        data_grupo = date(int(m["a"]), _MESES[m["m"]], int(m["d"]))
                    elif data_grupo is None:
                        raise LayoutInesperado(self.nome, "grupo_sem_data", num)
                    sinal = 1 if m["lado"] == "entradas" else -1
                    if (m["sinal"] == "+") != (sinal > 0):
                        raise LayoutInesperado(self.nome, "sinal_do_grupo", num)
                    segmentos.append(Segmento(f"grupo {data_grupo.isoformat()} {m['lado']}",
                                              Decimal(0), sinal * valor_br(m["v"])))
                    grupo = (len(segmentos) - 1, sinal)
                    continue
                if m := _SO_DATA.match(linha):
                    fecha_pendente()
                    data_grupo = date(int(m["a"]), _MESES[m["m"]], int(m["d"]))
                    grupo = None  # lançamento antes do "Total de …" é erro
                    continue
                if m := _LANCAMENTO.match(linha):
                    fecha_pendente()
                    if grupo is None or data_grupo is None:
                        raise LayoutInesperado(self.nome, "lancamento_fora_de_grupo", num)
                    idx_lado = extrato.idx_entradas if grupo[1] > 0 else extrato.idx_saidas
                    segs = (grupo[0], idx_lado, extrato.idx_extrato)
                    pendente = [num, data_grupo, grupo[1], segs, m["texto"], valor_br(m["v"])]
                    continue
                # continuação do complemento do lançamento anterior
                if pendente is None:
                    raise LayoutInesperado(self.nome, "linha_solta", num)
                pendente[4] += " " + linha.strip()
        fecha_pendente()
        if not transacoes:
            raise LayoutInesperado(self.nome, "arquivo_sem_lancamentos")
        if len(titulares) != 1:
            raise LayoutInesperado(self.nome, "titular_diferente_entre_paginas")
        return ResultadoExtracao(self.banco, self.produto, transacoes, segmentos, sorted(titulares))

    def _le_resumo(self, corpo: list[str], segmentos: list[Segmento], num: int) -> tuple[_Extrato, list[str]]:
        extrato = _Extrato()
        for i, linha in enumerate(corpo):
            if linha == "Movimentações":
                break
            chave = next((k for k, rx in _RESUMO.items() if rx.match(linha)), None)
            if chave is not None:
                if chave in extrato.resumo:
                    if chave != "final" or extrato.resumo[chave] != valor_br(_RESUMO[chave].match(linha)["v"]):
                        raise LayoutInesperado(self.nome, "resumo_repetido", num)
                extrato.resumo[chave] = valor_br(_RESUMO[chave].match(linha)["v"])
            elif linha not in _RESUMO_FIXAS:
                raise LayoutInesperado(self.nome, "linha_desconhecida_no_resumo", num)
        else:
            raise LayoutInesperado(self.nome, "resumo_sem_movimentacoes", num)
        if set(extrato.resumo) != set(_RESUMO):
            raise LayoutInesperado(self.nome, "resumo_incompleto", num)
        r = extrato.resumo
        n = len(segmentos)
        segmentos += [
            Segmento(f"extrato {n} saldo", r["inicial"] + r["rendimento"], r["final"]),
            Segmento(f"extrato {n} entradas", Decimal(0), r["entradas"]),
            Segmento(f"extrato {n} saidas", Decimal(0), r["saidas"]),
        ]
        extrato.idx_extrato, extrato.idx_entradas, extrato.idx_saidas = n, n + 1, n + 2
        return extrato, corpo[i + 1:]

    def _monta(self, pagina: int, data: date, sinal: int, segs: tuple[int, ...], texto: str,
               valor: Decimal) -> TransacaoBruta:
        texto = nu.desfaz_intercalacao(re.sub(r"\s+", " ", texto).strip())
        tipo, resto = nu.separa_tipo(texto)
        nome = doc = ""
        if tipo in nu.TIPOS:
            if nu.TIPOS[tipo].sinal != sinal:
                raise LayoutInesperado(self.nome, "tipo_no_grupo_errado", pagina)
            try:
                nome, doc = nu.contraparte(tipo, resto)
            except nu.ComplementoInvalido as exc:
                raise LayoutInesperado(self.nome, str(exc), pagina) from None
        return TransacaoBruta(data, tipo, sinal * valor, segs, nome, doc, pagina=pagina)
