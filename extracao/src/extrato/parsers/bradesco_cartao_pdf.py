"""Cartão Bradesco: faturas em PDF mescladas (2 páginas por fatura).

Regra de páginas (definida com o usuário em 2026-11-04): a cada 2 páginas, a 2ª ("Página 2 de 2")
traz os lançamentos; a 1ª ("Página 1 de 2") traz só o resumo, usado aqui para a conferência.

Página 1: "Saldo anterior…… R$ S", "(-) …/Pagamentos…… R$ P", "(+)Compras/……… R$ C",
"(=)Total……… R$ T" e o vencimento (DD/MM/AAAA logo abaixo de "Total de fatura Vencimento").
Página 2: duas colunas; os lançamentos ficam na da esquerda, lida pela posição das palavras:
    Data | Histórico de Lançamentos | Cidade | US$ | R$      (valor com "-" no fim = crédito)
Bloco de cada portador: "NOME  Cartão 9999 XXXX XXXX 9999" … "Total NOME valor".
Fim: "Total da fatura em real valor".

Reconciliação, por fatura (rejeitada sozinha se não fechar):
    débitos listados == C; créditos listados == P; lançamentos do portador == subtotal;
    S − P + C == T; "Total da fatura em real" == T.
Fora do CSV (mas na conferência): pagamento da fatura (já está no extrato da conta).
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

_NUM = r"\d{1,3}(?:\.\d{3})*,\d{2}"
_VALOR = re.compile(rf"^{_NUM}-?$")
_DATA = re.compile(r"^\d{2}/\d{2}$")
_PAGINA = re.compile(r"P[áa]gina (\d) de 2")
_RESUMO = {
    "saldo": re.compile(rf"^Saldo anterior\.+ R\$ (?P<v>{_NUM})-?$"),
    "pagamentos": re.compile(rf"^\(-\) ?\S*Pagamentos\.+ R\$ (?P<v>{_NUM})$"),
    "compras": re.compile(rf"^\(\+\) ?Compras\S*\.+ R\$ (?P<v>{_NUM})$"),
    "total": re.compile(rf"^\(=\) ?Total\.+ R\$ (?P<v>{_NUM})$"),
}
_VENCIMENTO = re.compile(rf"^R\$ {_NUM} (?P<d>\d{{2}}/\d{{2}}/\d{{4}}) R\$")
_COLUNA_ESQUERDA = 358.0  # pt: a coluna da direita (resumo/taxas) começa em ~362
_TOL_LINHA = 1.5
_TOL_VALOR = (5.0, 15.0)  # valor alinhado à direita do "R$" do cabeçalho (o "-" passa um pouco)

_PAGAMENTO = re.compile(r"^PAG(?:TO)?\b")
_PARCELA = re.compile(r"\s*\d{2}/\d{2}$")  # "LOJA 03/10" ou colado "LOJA*X03/10"
_FINANCEIRO: list[tuple[re.Pattern[str], str, Meio]] = [
    (re.compile(r"^ANUIDADE\b"), "ANUIDADE", Meio.TARIFA),
    (re.compile(r"^(?:IOF)\b"), "IOF", Meio.JUROS_IOF),
    (re.compile(r"^(?:JUROS|ENCARGOS|MULTA|MORA)\b"), "JUROS E ENCARGOS", Meio.JUROS_IOF),
    (re.compile(r"^ESTORNO\b"), "ESTORNO", Meio.ESTORNO),
]
# começo típico de lançamento do banco: se não for um dos conhecidos, é histórico desconhecido
_PARECE_DO_BANCO = re.compile(r"^(?:TARIFA|SEGURO|AJUSTE|CRED(?:ITO)?|DEB(?:ITO)?|SALDO|DEVOLUCAO|PROTECAO|"
                              r"SAQUE|TAXA|PARCELAMENTO|ROTATIVO)\b")
_MEIOS = {normaliza_historico(h): m for h, m in [
    ("COMPRA NO CRÉDITO", Meio.CARTAO_CREDITO),
    ("COMPRA PARCELADA", Meio.CARTAO_CREDITO),
    ("ESTORNO DE COMPRA", Meio.ESTORNO),
    ("PAGAMENTO DA FATURA", Meio.PAGAMENTO_FATURA),
    *[(h, m) for _, h, m in _FINANCEIRO],
]}


@dataclass
class _Linha:
    top: float
    palavras: list[dict]

    def texto(self, x_min: float = -1, x_max: float = 1e9) -> str:
        return " ".join(w["text"] for w in self.palavras if w["x0"] >= x_min and w["x1"] <= x_max)


@dataclass
class _Fatura:
    pagina: int
    vencimento: date
    resumo: dict[str, Decimal]
    lancamentos: list[tuple[int, date, str, Decimal, int | None]] = field(default_factory=list)
    portadores: list[Decimal] = field(default_factory=list)
    total_pagina2: Decimal | None = None


class BradescoCartaoPdf(Parser):
    nome = "bradesco_cartao_pdf"
    banco = "bradesco"
    produto = "cartao"
    MEIOS = _MEIOS
    REJEITA_POR_DOCUMENTO = True

    @classmethod
    def detecta(cls, caminho: Path) -> bool:
        if caminho.suffix.lower() != ".pdf":
            return False
        paginas = texto_pdf(caminho, 1)
        if not paginas:
            return False
        t = paginas[0]
        return ("Fatura Mensal" in t and bool(_PAGINA.search(t)) and "Total de fatura Vencimento" in t
                and any(rx.match(l) for l in t.splitlines() for rx in (_RESUMO["saldo"],)))

    def extrai(self, caminho: Path) -> ResultadoExtracao:
        import pdfplumber

        faturas: list[_Fatura] = []
        titulares: set[str] = set()
        with pdfplumber.open(caminho) as pdf:
            if len(pdf.pages) % 2:
                raise LayoutInesperado(self.nome, "numero_de_paginas_impar")
            for k in range(0, len(pdf.pages), 2):
                p1, p2 = pdf.pages[k], pdf.pages[k + 1]
                t1, t2 = p1.extract_text() or "", p2.extract_text() or ""
                m1, m2 = _PAGINA.search(t1), _PAGINA.search(t2)
                if not (m1 and m1.group(1) == "1" and m2 and m2.group(1) == "2"):
                    raise LayoutInesperado(self.nome, "par_de_paginas", k + 1)
                fat = self._le_resumo(t1, k + 1)
                self._le_lancamentos(p2, k + 2, fat, titulares)
                faturas.append(fat)
        return self._resultado(faturas, sorted(titulares))

    # --- página 1 ---

    def _le_resumo(self, texto: str, num: int) -> _Fatura:
        resumo: dict[str, Decimal] = {}
        vencimento: date | None = None
        linhas = texto.splitlines()
        for i, l in enumerate(linhas):
            for chave, rx in _RESUMO.items():
                if (m := rx.match(l)) and chave not in resumo:
                    v = valor_br(m["v"])
                    resumo[chave] = -v if chave == "saldo" and l.endswith("-") else v
            if l.startswith("Total de fatura Vencimento") and i + 1 < len(linhas):
                if m := _VENCIMENTO.match(linhas[i + 1]):
                    vencimento = datetime.strptime(m["d"], "%d/%m/%Y").date()
        if set(resumo) != set(_RESUMO):
            raise LayoutInesperado(self.nome, "resumo_incompleto", num)
        if vencimento is None:
            raise LayoutInesperado(self.nome, "vencimento", num)
        return _Fatura(num, vencimento, resumo)

    # --- página 2 ---

    def _le_lancamentos(self, pagina, num: int, fat: _Fatura, titulares: set[str]) -> None:
        linhas = self._linhas([w for w in pagina.extract_words() if w["x1"] <= _COLUNA_ESQUERDA])
        cab = next((l for l in linhas if l.texto().startswith("Data Histórico de Lançamentos")), None)
        if cab is None:
            raise LayoutInesperado(self.nome, "cabecalho_dos_lancamentos", num)
        ws = cab.palavras
        textos = [w["text"] for w in ws]
        i_lanc = textos.index("Lançamentos")
        x_hist = ws[textos.index("Histórico")]["x0"] - 2
        x_cidade = ws[i_lanc + 1]["x0"] - 2  # coluna logo após "Lançamentos" (cidade)
        x_rs = ws[-1]["x1"]  # último título: "R$"
        x_usd = ws[-2]["x1"]  # penúltimo: "US$"

        bloco: int | None = None
        for l in linhas:
            if l.top <= cab.top:
                continue
            t = [w["text"] for w in l.palavras]
            valores = [w for w in l.palavras if _VALOR.match(w["text"])
                       and x_rs - _TOL_VALOR[0] <= w["x1"] <= x_rs + _TOL_VALOR[1]]
            if t[0] == "Total":
                if not valores:
                    raise LayoutInesperado(self.nome, "total_sem_valor", num)
                v = self._valor(valores[-1]["text"])
                if t[1:4] == ["da", "fatura", "em"]:
                    fat.total_pagina2 = v
                elif bloco is not None:
                    fat.portadores[bloco] = v
                    bloco = None
                else:
                    raise LayoutInesperado(self.nome, "subtotal_sem_portador", num)
                continue
            if "Cartão" in t and l.palavras[t.index("Cartão")]["x0"] >= x_cidade - 10:
                nome = " ".join(w["text"] for w in l.palavras if w["x1"] <= l.palavras[t.index("Cartão")]["x0"])
                if nome:
                    titulares.add(nome)
                fat.portadores.append(Decimal("NaN"))  # preenchido pelo "Total NOME"
                bloco = len(fat.portadores) - 1
                continue
            if _DATA.match(t[0]) and l.palavras[0]["x0"] < x_hist - 5:  # data começa antes do histórico
                if len(valores) != 1:
                    raise LayoutInesperado(self.nome, "lancamento_sem_valor_unico", num)
                if any(_VALOR.match(w["text"]) and abs(w["x1"] - x_usd) <= 15 for w in l.palavras):
                    raise LayoutInesperado(self.nome, "lancamento_em_dolar", num)  # não visto ainda
                historico = l.texto(x_min=x_hist, x_max=x_cidade)
                if not historico:
                    raise LayoutInesperado(self.nome, "lancamento_sem_historico", num)
                data = self._data(t[0], fat.vencimento, num)
                fat.lancamentos.append((num, data, historico, self._valor(valores[0]["text"]), bloco))
                continue
            if any(_VALOR.match(w["text"]) for w in valores):
                raise LayoutInesperado(self.nome, "valor_fora_de_lancamento", num)
            # demais linhas da coluna: título, mensagens e texto legal

    @staticmethod
    def _linhas(palavras: list[dict]) -> list[_Linha]:
        linhas: list[_Linha] = []
        for w in sorted(palavras, key=lambda w: (w["top"], w["x0"])):
            if linhas and w["top"] - linhas[-1].top <= _TOL_LINHA:
                linhas[-1].palavras.append(w)
            else:
                linhas.append(_Linha(w["top"], [w]))
        for l in linhas:
            l.palavras.sort(key=lambda w: w["x0"])
        return linhas

    @staticmethod
    def _valor(texto: str) -> Decimal:
        """Valor como na fatura: cobrança > 0, crédito ("999,99-") < 0."""
        return valor_br(texto)

    def _data(self, ddmm: str, vencimento: date, num: int) -> date:
        """Ano da data DD/MM: o mais recente que não passa do vencimento.

        Parcelas mostram a data da compra original, que pode ser do mesmo mês do vencimento
        mas de um ano antes (ex.: vencimento 05/10, parcela de compra feita em 12/10 do ano anterior).
        """
        dia, mes = int(ddmm[:2]), int(ddmm[3:])
        try:
            d = date(vencimento.year, mes, dia)
            if d > vencimento:
                d = date(vencimento.year - 1, mes, dia)
        except ValueError:
            raise LayoutInesperado(self.nome, "data", num) from None
        return d

    # --- montagem e conferência ---

    def _resultado(self, faturas: list[_Fatura], titulares: list[str]) -> ResultadoExtracao:
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
                Segmento(f"{doc} débitos", Decimal(0), -r["compras"], doc),
                Segmento(f"{doc} créditos", Decimal(0), r["pagamentos"], doc),
                # sem lançamentos: só fecham se o próprio resumo for coerente
                Segmento(f"{doc} resumo", r["saldo"] - r["pagamentos"] + r["compras"], r["total"], doc),
                Segmento(f"{doc} total da página 2", f.total_pagina2 if f.total_pagina2 is not None
                         else Decimal("NaN"), r["total"], doc),
            ]
            i_port = len(segmentos)
            segmentos += [Segmento(f"{doc} portador {j}", Decimal(0), -sub, doc)
                          for j, sub in enumerate(f.portadores)]
            for num, data, historico, v, bloco in f.lancamentos:
                h, contraparte, omitida = self._classifica(historico, v)
                segs: tuple[int, ...] = (i0 if v > 0 else i0 + 1,)
                if bloco is not None:
                    segs += (i_port + bloco,)
                transacoes.append(TransacaoBruta(data, h, -v, segs, contraparte, pagina=num,
                                                 omitida=omitida or v == 0))
        return ResultadoExtracao(self.banco, self.produto, transacoes, segmentos, titulares)

    @staticmethod
    def _classifica(historico: str, v: Decimal) -> tuple[str, str, bool]:
        """(histórico canônico, contraparte, omitida). v como na fatura (cobrança > 0)."""
        if _PAGAMENTO.match(historico):
            return "PAGAMENTO DA FATURA", "", True
        for rx, h, _ in _FINANCEIRO:
            if rx.match(historico):
                return h, "", False
        if _PARECE_DO_BANCO.match(historico):
            return historico, "", False  # lançamento do banco desconhecido: o mapa rejeita
        parcelada = bool(_PARCELA.search(historico))
        loja = _PARCELA.sub("", historico).strip()
        if v < 0:
            return "ESTORNO DE COMPRA", loja, False
        return ("COMPRA PARCELADA" if parcelada else "COMPRA NO CRÉDITO"), loja, False
