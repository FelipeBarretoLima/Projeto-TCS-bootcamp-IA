"""Cartão Nubank: faturas em PDF (uma ou várias mescladas no mesmo arquivo).

Cada fatura começa por uma capa ("<nome>, …" / "Esta é a sua fatura de" / … / "Data de vencimento:
DD MMM AAAA"). Depois: página de RESUMO DA FATURA, a seção "TRANSAÇÕES DE DD MMM A DD MMM"
e páginas de texto padrão. Páginas internas começam por "NOME DO TITULAR" / "FATURA DD MMM AAAA
EMISSÃO E ENVIO …". Na seção de transações há blocos por portador ("NOME R$ subtotal") e o bloco
"Pagamentos e Financiamentos"; lançamento = "DD MMM descrição [−]R$ valor" (sem ano).

Reconciliação, por fatura (dados do próprio resumo, que a Nubank declara):
  cobranças listadas == soma dos itens do resumo exceto "Fatura anterior", "Pagamento recebido",
                         "Saldo financiado" (dívida anterior que foi para financiamento) e o total;
  pagamentos listados == "Pagamento recebido";
  lançamentos de cada portador == subtotal do portador.
O "Total a pagar" não entra: ele depende de crédito acumulado de faturas anteriores e de
financiamento (regras do banco que não aparecem lançamento a lançamento).

Fora do CSV (mas dentro da reconciliação): pagamento da fatura (já está no extrato da conta),
saldo restante da fatura anterior e movimentos de saldo do rotativo.
Sinal: cobrança na fatura vira saída (negativo); crédito na fatura vira entrada (positivo).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..modelos import Meio
from ..normalizacao import normaliza_historico, valor_br
from .base import LayoutInesperado, Parser, ResultadoExtracao, Segmento, TransacaoBruta, texto_pdf

_MESES = {m: i for i, m in enumerate("JAN FEV MAR ABR MAI JUN JUL AGO SET OUT NOV DEZ".split(), start=1)}
_M = "(?:" + "|".join(_MESES) + ")"
_NUM = r"\d{1,3}(?:\.\d{3})*,\d{2}"
_V = rf"(?P<s>[−-])?R\$ (?P<v>{_NUM})"

_CAPA = re.compile(r"^.+ é a .+ fatura de$")  # 2ª linha da capa
_VENCIMENTO = re.compile(rf"^Data de vencimento: (?P<d>\d{{2}}) (?P<m>{_M}) (?P<a>\d{{4}})$")
_CAB_INTERNO = re.compile(rf"^FATURA \d{{2}} {_M} \d{{4}} EMISSÃO E ENVIO \d{{2}} {_M} \d{{4}}$")
_SECAO = re.compile(rf"^TRANSAÇÕES DE \d{{2}} {_M} A \d{{2}} {_M}$")
_LANCAMENTO = re.compile(rf"^(?P<dd>\d{{2}}) (?P<mm>{_M}) (?P<d>.+?) {_V}$")
_PARECE_LANCAMENTO = re.compile(rf"^\d{{2}} {_M} ")
# cabeçalho de bloco de portador: "Nome do Portador R$ subtotal" (rótulo sem dígitos), seguido de lançamento
_PORTADOR = re.compile(rf"^(?P<nome>[^\W\d_][^\d•$]*?) R\$ (?P<v>{_NUM})$")
_BLOCO_PAGAMENTOS = re.compile(rf"^Pagamentos(?: e Financiamentos)? {_V}$")
_ITEM_RESUMO = re.compile(rf"^(?P<t>.+?) {_V}$")
_FIM_RESUMO = ("Pagamento mínimo", "O Nubank")
# rótulos do resumo (minúsculas, até a vírgula) -> entra na soma das cobranças?
_RESUMO: dict[str, bool] = {
    "fatura anterior": False,
    "pagamento recebido": False,
    "saldo financiado": False,
    "total a pagar": False,
    "total de compras de todos os cartões": True,
    "outros lançamentos": True,
    "juros de financiamento": True,
    "iof de financiamento": True,
    "iof de compras internacionais": True,
    "estorno de juros": True,
}

# descrições fixas -> (histórico, meio, omitida)
_FIXOS: dict[str, tuple[str, Meio, bool]] = {
    "Saldo restante da fatura anterior": ("SALDO RESTANTE DA FATURA ANTERIOR", Meio.OUTROS, True),
    "Saldo em rotativo": ("SALDO EM ROTATIVO", Meio.OUTROS, True),
    "Crédito de rotativo": ("CRÉDITO DE ROTATIVO", Meio.OUTROS, True),
    "Encerramento de dívida": ("ENCERRAMENTO DE DÍVIDA", Meio.OUTROS, True),
    "IOF de rotativo": ("IOF DE ROTATIVO", Meio.JUROS_IOF, False),
    "Juros de rotativo": ("JUROS DE ROTATIVO", Meio.JUROS_IOF, False),
    "Juros de dívida encerrada": ("JUROS DE DÍVIDA ENCERRADA", Meio.JUROS_IOF, False),
}
_PAGAMENTO = re.compile(rf"^Pagamento em \d{{2}} {_M}$")
_ESTORNO_JUROS = re.compile(r"^Estorno de juros\b")
_ESTORNO_COMPRA = re.compile(r'^Estorno de (?:"(?P<loja>.+)"|(?P<loja_nupay>.+?)(?: - NuPay)+)$')
_IOF_INTERNACIONAL = re.compile(r'^IOF de ".+"$')  # IOF cobrado sobre uma compra no exterior
# começo de descrição que indica lançamento financeiro: se não for um dos conhecidos, é erro
_FINANCEIRO = re.compile(r"^(?:Juros|IOF|Multa|Encargo|Saldo|Crédito|Estorno|Pagamento|Anuidade|Tarifa|"
                         r"Ajuste|Parcelamento|Encerramento|Financiamento)\b")
_CARTAO = re.compile(r"^•••• \d{4} ")
_PARCELA = re.compile(r" - Parcela \d+/\d+$")
_NUPAY = " - NuPay"

_MEIOS = {normaliza_historico(h): m for h, m, _ in _FIXOS.values()} | {
    normaliza_historico(h): m for h, m in [
        ("PAGAMENTO DA FATURA", Meio.PAGAMENTO_FATURA),
        ("ESTORNO DE JUROS", Meio.ESTORNO),
        ("IOF DE COMPRA INTERNACIONAL", Meio.JUROS_IOF),
        ("ESTORNO DE COMPRA", Meio.ESTORNO),
        ("COMPRA NO CRÉDITO", Meio.CARTAO_CREDITO),
        ("COMPRA PARCELADA", Meio.CARTAO_CREDITO),
        ("COMPRA NUPAY", Meio.CARTAO_CREDITO),
    ]
}


@dataclass
class _Fatura:
    pagina: int
    vencimento: date
    resumo: dict[str, Decimal] = field(default_factory=dict)
    lancamentos: list[tuple[int, date, str, Decimal, int | None]] = field(default_factory=list)
    portadores: list[tuple[str, Decimal]] = field(default_factory=list)
    secao: bool = False
    bloco: int | None = None  # portador em curso (None = fora de bloco de portador)


class NubankFaturaPdf(Parser):
    nome = "nubank_fatura_pdf"
    banco = "nubank"
    produto = "cartao"
    MEIOS = _MEIOS
    REJEITA_POR_DOCUMENTO = True  # cada fatura do arquivo é conferida e rejeitada sozinha

    @classmethod
    def detecta(cls, caminho: Path) -> bool:
        if caminho.suffix.lower() != ".pdf":
            return False
        paginas = texto_pdf(caminho, 1)
        if not paginas:
            return False
        ls = paginas[0].splitlines()
        return (len(ls) > 5 and bool(_CAPA.match(ls[1])) and any(_VENCIMENTO.match(l) for l in ls)
                and any(l.startswith("Limite total do cartão de crédito:") for l in ls))

    def extrai(self, caminho: Path) -> ResultadoExtracao:
        faturas: list[_Fatura] = []
        titulares: set[str] = set()
        for num, texto in enumerate(texto_pdf(caminho), start=1):
            ls = texto.splitlines()
            if len(ls) > 1 and _CAPA.match(ls[1]):
                venc = next((m for l in ls if (m := _VENCIMENTO.match(l))), None)
                if venc is None:
                    raise LayoutInesperado(self.nome, "capa_sem_vencimento", num)
                faturas.append(_Fatura(num, date(int(venc["a"]), _MESES[venc["m"]], int(venc["d"]))))
                continue
            if not faturas:
                raise LayoutInesperado(self.nome, "pagina_antes_da_capa", num)
            if len(ls) < 2 or not _CAB_INTERNO.match(ls[1]):
                raise LayoutInesperado(self.nome, "cabecalho_interno", num)
            titulares.add(ls[0].strip())
            self._le_pagina(ls[2:], num, faturas[-1], titulares)
        if not faturas:
            raise LayoutInesperado(self.nome, "sem_faturas")
        return self._resultado(faturas, sorted(titulares))

    def _le_pagina(self, linhas: list[str], num: int, fat: _Fatura, titulares: set[str]) -> None:
        if linhas and linhas[0].startswith("RESUMO DA FATURA"):
            if fat.resumo:
                raise LayoutInesperado(self.nome, "dois_resumos", num)
            for l in linhas[1:]:
                if l.startswith(_FIM_RESUMO):
                    break
                m = _ITEM_RESUMO.match(l)
                rotulo = m["t"].split(",")[0].lower() if m else ""
                if rotulo not in _RESUMO:
                    raise LayoutInesperado(self.nome, "item_de_resumo_desconhecido", num)
                fat.resumo[rotulo] = -valor_br(m["v"]) if m["s"] else valor_br(m["v"])
            if "total a pagar" not in fat.resumo:
                raise LayoutInesperado(self.nome, "resumo_sem_total", num)
            return
        for i, l in enumerate(linhas):
            if _SECAO.match(l):
                fat.secao = True
                continue
            if not fat.secao:
                continue
            if m := _LANCAMENTO.match(l):
                v = valor_br(m["v"])
                fat.lancamentos.append((num, self._data(m["dd"], m["mm"], fat.vencimento, num),
                                        m["d"], -v if m["s"] else v, fat.bloco))
                continue
            if _PARECE_LANCAMENTO.match(l):
                raise LayoutInesperado(self.nome, "lancamento_fora_do_formato", num)
            proxima_e_lancamento = i + 1 < len(linhas) and bool(_LANCAMENTO.match(linhas[i + 1]))
            if proxima_e_lancamento and not l.startswith("Pagamentos") and (m := _PORTADOR.match(l)):
                fat.portadores.append((m["nome"].strip(), valor_br(m["v"])))
                titulares.add(m["nome"].strip())
                fat.bloco = len(fat.portadores) - 1
            elif _BLOCO_PAGAMENTOS.match(l):
                fat.bloco = None
            # demais linhas da seção: texto explicativo/legal, sem lançamento

    def _data(self, dd: str, mm: str, vencimento: date, num: int) -> date:
        mes = _MESES[mm]
        ano = vencimento.year if mes <= vencimento.month else vencimento.year - 1
        try:
            d = date(ano, mes, int(dd))
        except ValueError:
            raise LayoutInesperado(self.nome, "data", num) from None
        if d > vencimento:
            raise LayoutInesperado(self.nome, "lancamento_depois_do_vencimento", num)
        return d

    def _resultado(self, faturas: list[_Fatura], titulares: list[str]) -> ResultadoExtracao:
        transacoes: list[TransacaoBruta] = []
        segmentos: list[Segmento] = []
        vistas: set[date] = set()
        for k, f in enumerate(faturas):
            if f.vencimento in vistas:
                raise LayoutInesperado(self.nome, "fatura_repetida", f.pagina)
            vistas.add(f.vencimento)
            if not f.resumo:
                raise LayoutInesperado(self.nome, "fatura_sem_resumo", f.pagina)
            rot = f"fatura {f.vencimento.isoformat()}"
            cobrancas = sum((v for t, v in f.resumo.items() if _RESUMO[t]), Decimal(0))
            i_cob, i_pag = len(segmentos), len(segmentos) + 1
            segmentos += [Segmento(f"{rot} cobranças", Decimal(0), -cobrancas, rot),
                          Segmento(f"{rot} pagamentos", Decimal(0), -f.resumo.get("pagamento recebido", Decimal(0)), rot)]
            i_port = len(segmentos)
            segmentos += [Segmento(f"{rot} portador {j}", Decimal(0), -sub, rot) for j, (_, sub) in enumerate(f.portadores)]
            for num, data, desc, v, bloco in f.lancamentos:
                historico, contraparte, omitida = self._classifica(desc, v)
                if historico == "SALDO RESTANTE DA FATURA ANTERIOR":
                    segs: tuple[int, ...] = ()  # já contado na fatura de origem
                elif historico == "PAGAMENTO DA FATURA":
                    segs = (i_pag,)
                else:
                    segs = (i_cob,)
                if bloco is not None:
                    segs += (i_port + bloco,)
                # linha de R$ 0,00 (ex.: juros zerados) não é movimento: fora do CSV
                transacoes.append(TransacaoBruta(data, historico, -v, segs, contraparte, pagina=num,
                                                 omitida=omitida or v == 0))
        return ResultadoExtracao(self.banco, self.produto, transacoes, segmentos, titulares)

    @staticmethod
    def _classifica(desc: str, v: Decimal) -> tuple[str, str, bool]:
        """(histórico, contraparte, omitida). v é o valor como na fatura (cobrança > 0)."""
        if desc in _FIXOS:
            h, _, omitida = _FIXOS[desc]
            return h, "", omitida
        if _PAGAMENTO.match(desc):
            return "PAGAMENTO DA FATURA", "", True
        if _ESTORNO_JUROS.match(desc):
            return "ESTORNO DE JUROS", "", False
        if _IOF_INTERNACIONAL.match(desc):
            return "IOF DE COMPRA INTERNACIONAL", "", False  # imposto do banco: sem contraparte
        if m := _ESTORNO_COMPRA.match(desc):
            return "ESTORNO DE COMPRA", m["loja"] or m["loja_nupay"], False
        if _FINANCEIRO.match(desc):
            return desc, "", False  # financeiro desconhecido: o mapa rejeita o arquivo
        loja = _CARTAO.sub("", desc)
        nupay = loja.endswith(_NUPAY)
        if nupay:
            loja = loja[: -len(_NUPAY)]
        parcelada = bool(_PARCELA.search(loja))
        loja = _PARCELA.sub("", loja)
        if v < 0:
            return "ESTORNO DE COMPRA", loja, False  # crédito de compra (cancelamento/devolução)
        return ("COMPRA NUPAY" if nupay else "COMPRA PARCELADA" if parcelada else "COMPRA NO CRÉDITO"), loja, False
