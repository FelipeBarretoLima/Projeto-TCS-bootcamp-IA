"""Conta corrente Bradesco: extrato do Internet Banking em PDF (um ou vários mesclados).

Cabeçalho de toda página:
    Bradesco …
    Data: DD/MM/AAAA - HHhMM
    Nome: NOME DO TITULAR
    Extrato de: Agência: 999 | Conta: 99999-9 Folha: n/N      ("Folha: 1/N" = início de um extrato)
    Data Histórico Docto. Crédito (R$) Débito (R$) Saldo (R$)
Tabela sem texto de coluna: o parser usa a posição das palavras. Cada lançamento tem uma
linha-âncora (documento, valor, saldo) e, 4–5 pt acima e abaixo, o histórico e o complemento
(DES:/REM:/estabelecimento). Histórico de uma linha só, sem complemento, fica na própria âncora.
A data só aparece no 1º lançamento do dia. Último lançamento do extrato: "Total créditos débitos saldo".

Sinal: pela coluna (Crédito/Débito), não pelo saldo. Reconciliação por extrato: cadeia de saldo
(por trechos, ver _trechos_de_saldo)
lançamento a lançamento + soma dos créditos == total + soma dos débitos == total; e o saldo do
Total == saldo do último lançamento.

Vários extratos no mesmo arquivo: o dia de fronteira entre dois extratos aparece nos dois.
Só é aceito se as duas cópias forem idênticas; a do extrato mais novo sai do CSV (duplicada).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..modelos import Meio
from ..normalizacao import normaliza_historico, valor_br
from .base import LayoutInesperado, Parser, ResultadoExtracao, Segmento, TransacaoBruta, texto_pdf

_NUM = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}-?$")
_DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_CAB = [
    re.compile(r"^Bradesco\b.*$"),
    re.compile(r"^Data: \d{2}/\d{2}/\d{4} - \d{2}h\d{2}$"),
    re.compile(r"^Nome: (?P<nome>.+)$"),
    re.compile(r"^Extrato de: Agência: \d+ \| Conta: [\d-]+ Folha: (?P<folha>\d+)/(?P<total>\d+)$"),
    re.compile(r"^Data Histórico Docto\. Crédito \(R\$\) Débito \(R\$\) Saldo \(R\$\)$"),
]
_TOL_COLUNA = 8.0  # pt: números são alinhados à direita da coluna
_TOL_LINHA = 1.5  # pt: palavras da mesma linha
_TOL_FAIXA = 7.0  # pt: histórico/complemento até 7 pt da âncora
_MAX_TRECHO = 15  # lançamentos: maior trecho aceito até o saldo impresso voltar a fechar

# histórico -> (meio, regra do complemento)
_TIPOS: dict[str, tuple[Meio, str]] = {
    "COMPRA ELO DEBITO VISTA": (Meio.CARTAO_DEBITO, "estabelecimento"),
    "COMPRA CARTAO VISA": (Meio.CARTAO_DEBITO, "estabelecimento"),
    "COMPRA DEBITO APP ELO": (Meio.CARTAO_DEBITO, "estabelecimento"),
    "COMPRA DEBITO APP VISA": (Meio.CARTAO_DEBITO, "estabelecimento"),
    "PIX ENVIADO": (Meio.PIX, "des"),
    "PIX QR CODE DINAMICO": (Meio.PIX, "des"),
    "PIX QR CODE ESTATICO": (Meio.PIX, "des"),
    "PIX RECEBIDO": (Meio.PIX, "rem"),
    "DEVOLUCAO PIX": (Meio.ESTORNO, "des_ou_rem"),
    "PAGTO ELETRON COBRANCA": (Meio.BOLETO, "empresa"),
    "PAGUE FACIL BRADESCO": (Meio.BOLETO, "empresa"),
    "PAGTO ELETRONICO TRIBUTO": (Meio.BOLETO, "ignora"),
    "CONTA DE LUZ": (Meio.BOLETO, "ignora"),
    "TRANSF CC PARA CC": (Meio.TED_DOC, "empresa"),
    "TED-TRANSF ELET DISPON": (Meio.TED_DOC, "ignora"),
    "TED C SAL P/ C CORRENTE": (Meio.SALARIO, "ignora"),
    "TRANSF SALDO C/SAL P/CC": (Meio.SALARIO, "ignora"),
    "CREDITO DE SALARIO": (Meio.SALARIO, "ignora"),
    "GASTOS CARTAO DE CREDITO": (Meio.PAGAMENTO_FATURA, "nenhum"),
    "RENTAB.INVEST FACILCRED*": (Meio.RENDIMENTO, "nenhum"),
    "RENDIMENTOS": (Meio.RENDIMENTO, "ignora"),
    "REGULARIZACAORENDIMENTO*": (Meio.RENDIMENTO, "ignora"),
    "RESGATE INVEST FACIL": (Meio.INVESTIMENTO, "nenhum"),
    "APLIC.INVEST FACIL": (Meio.INVESTIMENTO, "nenhum"),
    "RESG/VENCTO CDB": (Meio.INVESTIMENTO, "nenhum"),
    "APLICACAO CDB": (Meio.INVESTIMENTO, "nenhum"),
    "BAIXA AUTOMAT POUPANCA*": (Meio.TRANSFERENCIA_INTERNA, "nenhum"),
    "IOF S/ UTILIZACAO LIMITE": (Meio.JUROS_IOF, "nenhum"),
    "ENCARGOS LIMITE DE CRED": (Meio.JUROS_IOF, "ignora"),
    "TARIFA BANCARIA": (Meio.TARIFA, "ignora"),
    "SAQUE DINHEIRO BANCO 24H": (Meio.SAQUE, "ignora"),
    # tipos raros, mapeados com o usuário em 2026-11-04
    "APLICACAO INVESTIMENTOS": (Meio.INVESTIMENTO, "ignora"),
    "APLICACAO LCI": (Meio.INVESTIMENTO, "ignora"),
    "SALDO LIQ.INVEST FACIL*": (Meio.INVESTIMENTO, "ignora"),
    "CONTA DE TELEFONE": (Meio.BOLETO, "ignora"),
    "CONTA DE AGUA E ESGOTO": (Meio.BOLETO, "ignora"),
    "SAQUE DINHEIRO ATM": (Meio.SAQUE, "ignora"),
    "TRANSF AG/CONTA": (Meio.TRANSFERENCIA_INTERNA, "ignora"),
    "TRANSF ENTRE CONTAS": (Meio.TRANSFERENCIA_INTERNA, "ignora"),
    "TRANSFERENC. DE AGENCIA*": (Meio.TRANSFERENCIA_INTERNA, "ignora"),
    "TRANSFER SALDO POUPANCA": (Meio.TRANSFERENCIA_INTERNA, "ignora"),
}
_DES_REM = re.compile(r"^(?P<p>DES|REM): (?P<nome>.*?)(?: \d{2}/\d{2})?$")


@dataclass
class _Linha:
    top: float
    palavras: list[dict]

    def texto(self, x_min: float = -1, x_max: float = 1e9) -> str:
        return " ".join(w["text"] for w in self.palavras if w["x0"] >= x_min and w["x1"] <= x_max)


@dataclass
class _Lancamento:
    pagina: int
    data: date
    historico: str
    complemento: str
    documento: str
    valor: Decimal
    saldo: Decimal


@dataclass
class _Extrato:
    pagina_inicial: int
    folhas: int
    lancamentos: list[_Lancamento] = field(default_factory=list)
    total: tuple[Decimal, Decimal, Decimal] | None = None  # créditos, débitos, saldo


class BradescoContaPdf(Parser):
    nome = "bradesco_conta_pdf"
    banco = "bradesco"
    produto = "conta"
    MEIOS = {normaliza_historico(k): v[0] for k, v in _TIPOS.items()}

    @classmethod
    def detecta(cls, caminho: Path) -> bool:
        if caminho.suffix.lower() != ".pdf":
            return False
        paginas = texto_pdf(caminho, 1)
        return bool(paginas) and cls._cabecalho(paginas[0].splitlines()) is not None

    @staticmethod
    def _cabecalho(linhas: list[str]) -> list[re.Match[str]] | None:
        if len(linhas) < len(_CAB):
            return None
        ms = [rx.match(l) for rx, l in zip(_CAB, linhas)]
        return ms if all(ms) else None

    # --- leitura ---

    def extrai(self, caminho: Path) -> ResultadoExtracao:
        import pdfplumber

        extratos: list[_Extrato] = []
        titulares: set[str] = set()
        with pdfplumber.open(caminho) as pdf:
            for num, pagina in enumerate(pdf.pages, start=1):
                cab = self._cabecalho((pagina.extract_text() or "").splitlines())
                if cab is None:
                    raise LayoutInesperado(self.nome, "cabecalho", num)
                titulares.add(cab[2]["nome"].strip())
                folha, total_folhas = int(cab[3]["folha"]), int(cab[3]["total"])
                if folha == 1:
                    extratos.append(_Extrato(num, total_folhas))
                elif not extratos or folha != num - extratos[-1].pagina_inicial + 1 \
                        or total_folhas != extratos[-1].folhas:
                    raise LayoutInesperado(self.nome, "folhas_fora_de_sequencia", num)
                if extratos[-1].total is not None:
                    raise LayoutInesperado(self.nome, "pagina_depois_do_total", num)
                self._le_pagina(pagina, num, extratos[-1])
        for e in extratos:
            if e.total is None:
                raise LayoutInesperado(self.nome, "extrato_sem_total", e.pagina_inicial)
            if not e.lancamentos:
                raise LayoutInesperado(self.nome, "extrato_sem_lancamentos", e.pagina_inicial)
        return self._resultado(extratos, sorted(titulares))

    def _le_pagina(self, pagina, num: int, extrato: _Extrato) -> None:
        linhas = self._linhas(pagina.extract_words())
        i_cab = next((i for i, l in enumerate(linhas) if l.texto().startswith("Data Histórico Docto.")), None)
        if i_cab is None:
            raise LayoutInesperado(self.nome, "cabecalho_da_tabela", num)
        col = self._colunas(linhas[i_cab], num)
        corpo = linhas[i_cab + 1:]

        def numero_na(linha: _Linha, x1: float) -> list[dict]:
            return [w for w in linha.palavras if _NUM.match(w["text"]) and abs(w["x1"] - x1) <= _TOL_COLUNA]

        ancoras = [l for l in corpo if numero_na(l, col["saldo"])]
        usadas: set[int] = {id(a) for a in ancoras}
        data_atual = extrato.lancamentos[-1].data if extrato.lancamentos else None

        for a in ancoras:
            if extrato.total is not None:
                raise LayoutInesperado(self.nome, "lancamento_depois_do_total", num)
            cima = [l for l in corpo if id(l) not in usadas and a.top - _TOL_FAIXA <= l.top < a.top]
            baixo = [l for l in corpo if id(l) not in usadas and a.top < l.top <= a.top + _TOL_FAIXA]
            usadas.update(id(l) for l in cima + baixo)
            saldo = valor_br(numero_na(a, col["saldo"])[0]["text"])
            credito, debito = numero_na(a, col["credito"]), numero_na(a, col["debito"])

            if a.palavras[0]["text"] == "Total":
                if cima or baixo or len(credito) != 1 or len(debito) != 1:
                    raise LayoutInesperado(self.nome, "linha_de_total", num)
                extrato.total = (valor_br(credito[0]["text"]), valor_br(debito[0]["text"]), saldo)
                continue
            if len(credito) + len(debito) != 1:
                raise LayoutInesperado(self.nome, "valor_em_credito_e_debito", num)
            valor = valor_br((credito or debito)[0]["text"])
            if valor <= 0:
                raise LayoutInesperado(self.nome, "valor_nao_positivo_na_coluna", num)
            valor = valor if credito else -valor

            datas = [w["text"] for w in a.palavras if w["x1"] <= col["historico"] and _DATA.match(w["text"])]
            if datas:
                data_atual = datetime.strptime(datas[0], "%d/%m/%Y").date()
            if data_atual is None:
                raise LayoutInesperado(self.nome, "lancamento_sem_data", num)
            documento = " ".join(w["text"] for w in a.palavras
                                 if w["x0"] >= col["docto_ini"] and w["x1"] <= col["docto_fim"])
            faixa = dict(x_min=col["historico"], x_max=col["docto_ini"])
            if cima:
                historico = " ".join(l.texto(**faixa) for l in cima)
                complemento = " ".join(l.texto(**faixa) for l in baixo)
            else:
                if baixo:
                    raise LayoutInesperado(self.nome, "complemento_sem_historico", num)
                historico, complemento = a.texto(**faixa), ""
            extrato.lancamentos.append(_Lancamento(num, data_atual, historico, complemento, documento, valor, saldo))

        soltas = [l for l in corpo if id(l) not in usadas]
        if soltas:
            raise LayoutInesperado(self.nome, "linha_fora_de_lancamento", num)

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

    def _colunas(self, cab: _Linha, num: int) -> dict[str, float]:
        ws = cab.palavras
        textos = [w["text"] for w in ws]
        try:
            i_hist, i_doc = textos.index("Histórico"), textos.index("Docto.")
            i_cred, i_deb, i_sal = textos.index("Crédito"), textos.index("Débito"), textos.index("Saldo")
        except ValueError:
            raise LayoutInesperado(self.nome, "colunas", num) from None
        return {
            "historico": ws[i_hist]["x0"] - 2,
            "docto_ini": ws[i_hist]["x1"] + 100,  # documento fica bem à direita do histórico
            "docto_fim": ws[i_doc]["x1"] + _TOL_COLUNA,
            "credito": ws[i_cred + 1]["x1"],  # "(R$)" logo depois do nome da coluna
            "debito": ws[i_deb + 1]["x1"],
            "saldo": ws[i_sal + 1]["x1"],
        }

    # --- montagem e conferência ---

    def _resultado(self, extratos: list[_Extrato], titulares: list[str]) -> ResultadoExtracao:
        extratos = sorted(extratos, key=lambda e: e.lancamentos[0].data)
        duplicados = self._fronteiras(extratos)
        transacoes: list[TransacaoBruta] = []
        segmentos: list[Segmento] = []
        for k, e in enumerate(extratos):
            cred_total, deb_total, saldo_total = e.total
            if e.lancamentos[-1].saldo != saldo_total:
                raise LayoutInesperado(self.nome, "saldo_do_total_diferente_do_ultimo", e.pagina_inicial)
            i_cred, i_deb = len(segmentos), len(segmentos) + 1
            segmentos += [Segmento(f"extrato {k} créditos", Decimal(0), cred_total),
                          Segmento(f"extrato {k} débitos", Decimal(0), -deb_total)]
            for inicio, fim in self._trechos_de_saldo(e):
                abertura = e.lancamentos[inicio].saldo - e.lancamentos[inicio].valor if inicio == 0 \
                    else e.lancamentos[inicio - 1].saldo
                segmentos.append(Segmento(f"extrato {k} saldo {inicio}-{fim}", abertura, e.lancamentos[fim].saldo))
                for j in range(inicio, fim + 1):
                    l = e.lancamentos[j]
                    t = self._monta(l, (len(segmentos) - 1, i_cred if l.valor > 0 else i_deb))
                    transacoes.append(replace(t, duplicada=(k, j) in duplicados))
        return ResultadoExtracao(self.banco, self.produto, transacoes, segmentos, titulares)

    def _trechos_de_saldo(self, e: _Extrato) -> list[tuple[int, int]]:
        """Divide o extrato em trechos [início, fim] que fecham pelo saldo impresso.

        Quase sempre cada lançamento fecha sozinho (saldo anterior + valor == saldo). Em alguns
        pontos o Bradesco imprime saldos intermediários que não acompanham os lançamentos
        (movimentos automáticos não listados), mas o saldo volta a fechar poucas linhas depois:
        o trecho termina no primeiro lançamento em que fecha. Trecho maior que _MAX_TRECHO,
        ou que não fecha até o fim, rejeita o arquivo.
        """
        trechos: list[tuple[int, int]] = []
        ls = e.lancamentos
        inicio, soma = 0, Decimal(0)
        abertura = ls[0].saldo - ls[0].valor
        for j, l in enumerate(ls):
            soma += l.valor
            if abertura + soma == l.saldo:
                trechos.append((inicio, j))
                inicio, soma, abertura = j + 1, Decimal(0), l.saldo
            elif j - inicio + 1 > _MAX_TRECHO:
                raise LayoutInesperado(self.nome, "saldo_nao_fecha_em_trecho_curto", l.pagina)
        if inicio != len(ls):
            raise LayoutInesperado(self.nome, "saldo_nao_fecha_no_fim_do_extrato", ls[-1].pagina)
        return trechos

    def _fronteiras(self, extratos: list[_Extrato]) -> set[tuple[int, int]]:
        """(extrato, índice) das cópias repetidas no dia de fronteira entre extratos consecutivos."""
        chave = lambda l: (l.data, l.historico, l.complemento, l.documento, l.valor, l.saldo)
        duplicados: set[tuple[int, int]] = set()
        for k in range(1, len(extratos)):
            antes, depois = extratos[k - 1].lancamentos, extratos[k].lancamentos
            if antes[-1].data < depois[0].data:
                continue
            if antes[-1].data > depois[0].data:
                raise LayoutInesperado(self.nome, "extratos_sobrepostos", extratos[k].pagina_inicial)
            dia = depois[0].data
            fim = [chave(l) for l in antes if l.data == dia]
            ini = [chave(l) for l in depois if l.data == dia]
            if fim != ini:
                raise LayoutInesperado(self.nome, "dia_de_fronteira_diferente", extratos[k].pagina_inicial)
            duplicados.update((k, j) for j in range(len(ini)))
        return duplicados

    def _monta(self, l: _Lancamento, segs: tuple[int, ...]) -> TransacaoBruta:
        historico = l.historico
        if historico not in _TIPOS:
            return TransacaoBruta(l.data, historico, l.valor, segs, pagina=l.pagina)  # o mapa rejeita
        regra = _TIPOS[historico][1]
        nome = ""
        if regra in ("des", "rem", "des_ou_rem"):
            m = _DES_REM.match(l.complemento)
            if not m or (regra != "des_ou_rem" and m["p"].lower() != regra) or not m["nome"].strip():
                raise LayoutInesperado(self.nome, f"complemento_{regra}", l.pagina)
            nome = m["nome"].strip()
        elif regra in ("estabelecimento", "empresa"):
            if not l.complemento:
                raise LayoutInesperado(self.nome, f"complemento_{regra}", l.pagina)
            nome = l.complemento
        elif regra == "nenhum" and l.complemento:
            raise LayoutInesperado(self.nome, "complemento_inesperado", l.pagina)
        return TransacaoBruta(l.data, historico, l.valor, segs, nome, pagina=l.pagina)
