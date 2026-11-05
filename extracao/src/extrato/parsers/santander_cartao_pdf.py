"""Cartão Santander: faturas em PDF mescladas.

Cada fatura: capa (sem paginação), "1/N" (vencimento e total a pagar), "2/N" (lançamentos e
Resumo da Fatura) e, às vezes, "3/3" (texto legal). Regra de páginas (definida com o usuário em
2026-11-04): os lançamentos estão na página seguinte à "1/N" — a 3ª de cada grupo de 4.
Páginas que não pertencem a nenhum grupo "1/N" (ex.: uma fatura antiga, de outro layout, no fim do
arquivo) viram um documento rejeitado, registrado no relatório.

Página de lançamentos: duas colunas independentes (corte em x=300), lidas de cima para baixo.
Lançamento: "[ícone] DD/MM descrição [parcela DD/DD] [-]valor" (valor = número mais à direita).
Resumo da Fatura: Saldo Anterior; (+) Total … no Brasil; (+) Total … no Exterior;
(-) Total de pagamentos; (-) Total de créditos; (=) Saldo Desta Fatura.

Reconciliação, por fatura (rejeitada sozinha se não fechar):
    débitos listados == Brasil + Exterior; pagamentos listados == Total de pagamentos;
    demais créditos listados == Total de créditos; Saldo Anterior + débitos − pagamentos − créditos == Saldo.
Fora do CSV (mas na conferência): pagamento da fatura.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..modelos import Meio
from ..normalizacao import normaliza_historico, valor_br
from .base import LayoutInesperado, Parser, ResultadoExtracao, Segmento, TransacaoBruta, texto_pdf

_NUM_RX = r"-?\d{1,3}(?:\.\d{3})*,\d{2}"
_NUM = re.compile(rf"^{_NUM_RX}$")
_DATA = re.compile(r"^\d{2}/\d{2}$")
_ICONE = re.compile(r"^\d$")
_PAGINACAO = re.compile(r"^(\d)/(\d)$")
# "R$ total DD/MM/AAAA R$limite" ou "R$ total DD/MM/AAAA DD/MM/AAAA" (vencimento = 1ª data)
_VENCIMENTO = re.compile(rf"^R\$ {_NUM_RX} (?P<d>\d{{2}}/\d{{2}}/\d{{4}}) (?:R\$|\d{{2}}/\d{{2}}/\d{{4}})")
_TITULAR = re.compile(r"cartão SANTANDER (?P<nome>.+?) - \d{4}\b")
_CARTAO = re.compile(r"^(?P<nome>.+?) - \d{4} \S+ \S+ \d{4}\b")
_CORTE_COLUNA = 300.0
_TOL_LINHA = 2.0
_RESUMO = {
    "saldo": re.compile(r"^Saldo Anterior\b"),
    "brasil": re.compile(r"^\(\+\) Total .* no Brasil\b"),
    "exterior": re.compile(r"^\(\+\) Total .* no (?!Brasil)\S+"),
    "pagamentos": re.compile(r"^\(-\) Total de pagamentos\b"),
    "creditos": re.compile(r"^\(-\) Total de cr"),
    "total": re.compile(r"^\(=\) Saldo\b"),
}
_PAGAMENTO = re.compile(r"^PAGAMENTO DE FATURA\b")
_PARCELA = re.compile(r"\s*\d{2}/\d{2}$")
_FINANCEIRO: list[tuple[re.Pattern[str], str, Meio]] = [
    (re.compile(r"^ANUIDADE\b"), "ANUIDADE", Meio.TARIFA),
    (re.compile(r"^IOF\b"), "IOF", Meio.JUROS_IOF),
    (re.compile(r"^(?:JUROS|ENCARGOS|MULTA|MORA)\b"), "JUROS E ENCARGOS", Meio.JUROS_IOF),
    (re.compile(r"^ESTORNO\b"), "ESTORNO", Meio.ESTORNO),
]
_PARECE_DO_BANCO = re.compile(r"^(?:TARIFA|SEGURO|AJUSTE|CRED(?:ITO)?|DEB(?:ITO)?|SALDO|DEVOLUCAO|PROTECAO|"
                              r"SAQUE|TAXA|PARCELAMENTO|ROTATIVO|PAGAMENTO)\b")
_MEIOS = {normaliza_historico(h): m for h, m in [
    ("COMPRA NO CRÉDITO", Meio.CARTAO_CREDITO),
    ("COMPRA PARCELADA", Meio.CARTAO_CREDITO),
    ("ESTORNO DE COMPRA", Meio.ESTORNO),
    ("PAGAMENTO DA FATURA", Meio.PAGAMENTO_FATURA),
    *[(h, m) for _, h, m in _FINANCEIRO],
]}


@dataclass
class _Fatura:
    pagina: int
    vencimento: date
    resumo: dict[str, Decimal] = field(default_factory=dict)
    lancamentos: list[tuple[int, date, str, Decimal]] = field(default_factory=list)


class SantanderCartaoPdf(Parser):
    nome = "santander_cartao_pdf"
    banco = "santander"
    produto = "cartao"
    MEIOS = _MEIOS
    REJEITA_POR_DOCUMENTO = True

    @classmethod
    def detecta(cls, caminho: Path) -> bool:
        if caminho.suffix.lower() != ".pdf":
            return False
        paginas = texto_pdf(caminho, 2)
        if len(paginas) < 2:
            return False
        ls = paginas[1].splitlines()
        return (bool(ls) and bool(_PAGINACAO.match(ls[0].strip())) and ls[0].strip().startswith("1/")
                and "cartão SANTANDER" in paginas[1] and "Total a Pagar" in paginas[1])

    def extrai(self, caminho: Path) -> ResultadoExtracao:
        import pdfplumber

        textos = texto_pdf(caminho)
        faturas: list[_Fatura] = []
        titulares: set[str] = set()
        cobertas: set[int] = set()  # páginas (1-based) que pertencem a algum grupo reconhecido
        with pdfplumber.open(caminho) as pdf:
            for i, t in enumerate(textos):
                ls = t.splitlines()
                m = _PAGINACAO.match(ls[0].strip()) if ls else None
                if not (m and m.group(1) == "1"):
                    continue
                total_pags = int(m.group(2))
                num = i + 1  # página "1/N"
                if num + 1 > len(textos):
                    raise LayoutInesperado(self.nome, "fatura_sem_pagina_de_lancamentos", num)
                cobertas.update(range(num - 1, num + total_pags))  # capa + N páginas
                fat = self._le_capa_interna(t, num, titulares)
                self._le_lancamentos(pdf.pages[i + 1], num + 1, fat, titulares)
                faturas.append(fat)
        if not faturas:
            raise LayoutInesperado(self.nome, "sem_faturas")
        soltas = sorted(set(range(1, len(textos) + 1)) - cobertas)
        return self._resultado(faturas, sorted(titulares), soltas)

    # --- página 1/N ---

    def _le_capa_interna(self, texto: str, num: int, titulares: set[str]) -> _Fatura:
        venc = next((m for l in texto.splitlines() if (m := _VENCIMENTO.match(l))), None)
        if venc is None:
            raise LayoutInesperado(self.nome, "vencimento", num)
        if m := _TITULAR.search(texto):
            titulares.add(m["nome"].strip())
        return _Fatura(num, datetime.strptime(venc["d"], "%d/%m/%Y").date())

    # --- página de lançamentos ---

    def _le_lancamentos(self, pagina, num: int, fat: _Fatura, titulares: set[str]) -> None:
        palavras = pagina.extract_words()
        for coluna in ([w for w in palavras if w["x0"] < _CORTE_COLUNA],
                       [w for w in palavras if w["x0"] >= _CORTE_COLUNA]):
            for linha in self._linhas(coluna):
                self._le_linha(linha, num, fat, titulares)
        if set(fat.resumo) != set(_RESUMO):
            raise LayoutInesperado(self.nome, "resumo_incompleto", num)

    def _le_linha(self, ws: list[dict], num: int, fat: _Fatura, titulares: set[str]) -> None:
        t = [w["text"] for w in ws]
        txt = " ".join(t)
        nums = [w for w in ws if _NUM.match(w["text"])]
        chave = next((k for k, rx in _RESUMO.items() if rx.match(txt)), None)
        if chave is not None:
            if len(nums) != 1 or chave in fat.resumo:
                raise LayoutInesperado(self.nome, f"resumo_{chave}", num)
            fat.resumo[chave] = valor_br(nums[0]["text"])
            return
        if m := _CARTAO.match(txt):
            titulares.add(m["nome"].strip())
            return
        i = 1 if len(t) > 1 and _ICONE.match(t[0]) and _DATA.match(t[1]) else 0
        if _DATA.match(t[i]):
            if len(nums) != 1 or ws[-1] is not nums[0]:
                raise LayoutInesperado(self.nome, "lancamento_sem_valor_unico_no_fim", num)
            desc = " ".join(t[i + 1:-1])
            if not desc:
                raise LayoutInesperado(self.nome, "lancamento_sem_descricao", num)
            fat.lancamentos.append((num, self._data(t[i], fat.vencimento, num), desc, valor_br(nums[0]["text"])))
            return
        # demais linhas: títulos, cabeçalhos de tabela, VALOR TOTAL por cartão, quadro de
        # parcelamentos futuros e texto legal — nenhuma é lançamento

    @staticmethod
    def _linhas(palavras: list[dict]) -> list[list[dict]]:
        linhas: list[list[dict]] = []
        topo: list[float] = []
        for w in sorted(palavras, key=lambda w: (w["top"], w["x0"])):
            if linhas and w["top"] - topo[-1] <= _TOL_LINHA:
                linhas[-1].append(w)
            else:
                linhas.append([w])
                topo.append(w["top"])
        return [sorted(l, key=lambda w: w["x0"]) for l in linhas]

    def _data(self, ddmm: str, vencimento: date, num: int) -> date:
        """O ano mais recente que não passa do vencimento (parcelas trazem a data da compra)."""
        dia, mes = int(ddmm[:2]), int(ddmm[3:])
        try:
            d = date(vencimento.year, mes, dia)
            return d if d <= vencimento else date(vencimento.year - 1, mes, dia)
        except ValueError:
            raise LayoutInesperado(self.nome, "data", num) from None

    # --- montagem e conferência ---

    def _resultado(self, faturas: list[_Fatura], titulares: list[str], soltas: list[int]) -> ResultadoExtracao:
        transacoes: list[TransacaoBruta] = []
        segmentos: list[Segmento] = []
        vistas: set[date] = set()
        for f in faturas:
            if f.vencimento in vistas:
                raise LayoutInesperado(self.nome, "fatura_repetida", f.pagina)
            vistas.add(f.vencimento)
            doc = f"fatura {f.vencimento.isoformat()}"
            r = f.resumo
            i0 = len(segmentos)
            segmentos += [
                Segmento(f"{doc} débitos", Decimal(0), -(r["brasil"] + r["exterior"]), doc),
                Segmento(f"{doc} pagamentos", Decimal(0), r["pagamentos"], doc),
                Segmento(f"{doc} créditos", Decimal(0), r["creditos"], doc),
                # sem lançamentos: só fecha se o próprio resumo for coerente
                Segmento(f"{doc} resumo", r["saldo"] + r["brasil"] + r["exterior"] - r["pagamentos"] - r["creditos"],
                         r["total"], doc),
            ]
            for num, data, desc, v in f.lancamentos:
                h, contraparte, omitida = self._classifica(desc, v)
                seg = i0 if v > 0 else (i0 + 1 if h == "PAGAMENTO DA FATURA" else i0 + 2)
                transacoes.append(TransacaoBruta(data, h, -v, (seg,), contraparte, pagina=num,
                                                 omitida=omitida or v == 0))
        if soltas:
            # páginas fora de qualquer grupo "1/N" (ex.: fatura de layout antigo): documento rejeitado
            doc = f"páginas {soltas[0]}-{soltas[-1]} fora do layout (ignoradas)"
            segmentos.append(Segmento(doc, Decimal("NaN"), Decimal(0), doc))
        return ResultadoExtracao(self.banco, self.produto, transacoes, segmentos, titulares)

    @staticmethod
    def _classifica(desc: str, v: Decimal) -> tuple[str, str, bool]:
        """(histórico canônico, contraparte, omitida). v como na fatura (cobrança > 0)."""
        if _PAGAMENTO.match(desc):
            return "PAGAMENTO DA FATURA", "", True
        for rx, h, _ in _FINANCEIRO:
            if rx.match(desc):
                return h, "", False
        if _PARECE_DO_BANCO.match(desc):
            return desc, "", False  # lançamento do banco desconhecido: o mapa rejeita
        parcelada = bool(_PARCELA.search(desc))
        loja = _PARCELA.sub("", desc).strip()
        if v < 0:
            return "ESTORNO DE COMPRA", loja, False
        return ("COMPRA PARCELADA" if parcelada else "COMPRA NO CRÉDITO"), loja, False
