"""Conta corrente Sicoob: extrato em PDF.

Página 1:
    SICOOB / nome da cooperativa (2 linhas)
    DD/MM/AAAA EXTRATO CONTA CORRENTE HH:MM:SS
    COOP.: 9999-9 / SICOOB …
    CONTA: 99.999-9 / NOME DO TITULAR
    PERÍODO: DD/MM/AAAA - DD/MM/AAAA
    DATA DOCUMENTO HISTÓRICO VALOR
As outras páginas não têm cabeçalho. Lançamento: "DD/MM/AAAA [DOC] HISTÓRICO 1.234,56C|D",
com complemento nas linhas de baixo. Cada dia fecha com "SALDO DO DIA ===== > X C|D".
No fim, um resumo a partir de "(+) SALDO EM CONTA:".

Reconciliação: um segmento por dia, saldo anterior + lançamentos == saldo do dia.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..cidades import separa_cidade
from ..modelos import Meio
from ..normalizacao import normaliza_historico, valor_br
from .base import LayoutInesperado, Parser, ResultadoExtracao, Segmento, TransacaoBruta, texto_pdf

_NUM = r"\d{1,3}(?:\.\d{3})*,\d{2}"
_LANCAMENTO = re.compile(rf"^(?P<data>\d{{2}}/\d{{2}}/\d{{4}}) (?P<texto>.+?) (?P<v>{_NUM})(?P<cd>[CD*])$")
_SALDO_DIA = re.compile(rf"^SALDO DO DIA ===== > (?P<v>{_NUM})(?P<cd>[CD])$")
_FIM = "(+) SALDO EM CONTA:"
_SALDO_FINAL = re.compile(rf"^\(\+\) SALDO EM CONTA: (?P<v>{_NUM})(?P<cd>[CD])$")
_TITULAR = re.compile(r"^CONTA: [\d.]+-\d / (?P<nome>.+)$")
_CABECALHO = [
    re.compile(r"^SICOOB$"),
    None,  # nome da cooperativa
    None,
    re.compile(r"^\d{2}/\d{2}/\d{4} EXTRATO CONTA CORRENTE \d{2}:\d{2}:\d{2}$"),
    re.compile(r"^COOP\.: \d{4}-\d / SICOOB .+$"),
    _TITULAR,
    re.compile(r"^PERÍODO: \d{2}/\d{2}/\d{4} - \d{2}/\d{2}/\d{4}$"),
    re.compile(r"^DATA DOCUMENTO HISTÓRICO VALOR$"),
]

# histórico (como o Sicoob escreve) -> (meio, sinal esperado: -1, +1 ou 0 = qualquer, regra do complemento)
_TIPOS: dict[str, tuple[Meio, int, str]] = {
    "COMPRA MASTERCARD MAESTRO": (Meio.CARTAO_DEBITO, -1, "estabelecimento"),
    "DÉB.TIT.COMPE EFETIVADO": (Meio.BOLETO, -1, "ignora"),
    "CRÉD.LIQUIDAÇÃO COBRANÇA": (Meio.BOLETO, +1, "nenhum"),
    "TARIFA COBRANÇA": (Meio.TARIFA, -1, "nenhum"),
    "DÉBITO PACOTE SERVIÇOS": (Meio.TARIFA, -1, "nenhum"),
    "SAQUE NA AGENCIA": (Meio.SAQUE, -1, "ignora"),
    "SAQUE SEM CARTÃO": (Meio.SAQUE, -1, "ignora"),
    "DÉBITO SAQUE INTERCREDIS": (Meio.SAQUE, -1, "nenhum"),
    "PIX EMITIDO OUTRA IF": (Meio.PIX, -1, "pix"),
    "PIX EMITIDO OUTRA IF - MESMA TIT.": (Meio.TRANSFERENCIA_INTERNA, -1, "ignora"),
    "DÉB.TRANSF.CONTAS DIF.TITULARIDADE": (Meio.TED_DOC, -1, "favorecido"),
    "CRÉD.TRANSF.CONTAS": (Meio.TED_DOC, +1, "remetente"),
    "DEBITO EMISSÃO TED DIF.TITULARIDADE": (Meio.TED_DOC, -1, "nome_livre"),
    "TED INTERNET": (Meio.TED_DOC, 0, "nenhum"),
    "DÉB.CONV.TELECOMUNICAÇÕES": (Meio.BOLETO, -1, "nenhum"),
    "DÉB.CONV.SANEAMENTO": (Meio.BOLETO, -1, "nenhum"),
    "DÉB.CONV.EN.ELÉTRICA E GÁS": (Meio.BOLETO, -1, "nenhum"),
    "DÉB.CONV.ORGÃOS GOV.": (Meio.BOLETO, -1, "nenhum"),
    "DÉB.CONV.TRIBUTOS FEDERAIS - RFB": (Meio.BOLETO, -1, "nenhum"),
    "DÉB.CONV.DEMAIS EMPRESAS": (Meio.BOLETO, -1, "nenhum"),  # empresa vem antes, no próprio histórico
    "DÉBITO RECARGA PRÉ-PAGA": (Meio.OUTROS, -1, "nenhum"),
    "CRÉD.DISTRIBUIÇÃO SOBRAS/VALORES": (Meio.RENDIMENTO, +1, "nenhum"),
    "ADIANT.DEPOSITANTE": (Meio.OUTROS, 0, "nenhum"),
    "JUROS ADIANT.DEPOSITANTE": (Meio.JUROS_IOF, -1, "nenhum"),
    "DÉB.IOF": (Meio.JUROS_IOF, -1, "nenhum"),
}
_ORDEM = sorted(_TIPOS, key=len, reverse=True)
# "SEM PARAR DÉB.CONV.DEMAIS EMPRESAS": o nome da empresa fica antes do histórico
_CONVENIO_EMPRESA = re.compile(r"^(?P<empresa>.+?) DÉB\.CONV\.DEMAIS EMPRESAS$")
# documento: número, "Pix", "1234ATM", "Recarga" ou "IOF/1-2"; pode faltar
_DOC = re.compile(r"^(?:\d+|Pix|\d+ATM|Recarga|[A-Z]{3}/\d-\d)$")
_CNPJ_PIX = re.compile(r"^\d{2}\.\d{3}\.\d{3} \d{4}-\d{2}$")
_CPF_PIX = re.compile(r"^\*{3}\.\d{3}\.\d{3}-\*{2}$")


def _cd(valor: Decimal, cd: str) -> Decimal:
    return valor if cd == "C" else -valor


class SicoobContaPdf(Parser):
    nome = "sicoob_conta_pdf"
    banco = "sicoob"
    produto = "conta"
    MEIOS = {normaliza_historico(k): v[0] for k, v in _TIPOS.items()}

    @classmethod
    def detecta(cls, caminho: Path) -> bool:
        if caminho.suffix.lower() != ".pdf":
            return False
        paginas = texto_pdf(caminho, 1)
        return bool(paginas) and cls._cabecalho_ok(paginas[0].splitlines())

    @staticmethod
    def _cabecalho_ok(linhas: list[str]) -> bool:
        return len(linhas) > len(_CABECALHO) and all(
            rx is None or rx.match(l) for rx, l in zip(_CABECALHO, linhas)
        )

    def extrai(self, caminho: Path) -> ResultadoExtracao:
        paginas = texto_pdf(caminho)
        primeira = paginas[0].splitlines()
        if not self._cabecalho_ok(primeira):
            raise LayoutInesperado(self.nome, "cabecalho", 1)
        titular = _TITULAR.match(primeira[5])["nome"].strip()

        # todas as linhas do corpo, com a página de origem (só para mensagens de erro)
        corpo = [(1, l) for l in primeira[len(_CABECALHO):]]
        corpo += [(n, l) for n, p in enumerate(paginas[1:], start=2) for l in p.splitlines()]

        transacoes: list[TransacaoBruta] = []
        segmentos: list[Segmento] = []
        saldo: Decimal | None = None  # saldo de abertura do dia em curso
        pendente: list | None = None  # [pagina, data, historico, valor, complemento[]]
        i = 0
        while i < len(corpo):
            num, linha = corpo[i]
            i += 1
            if linha == "RESUMO" and pendente is None:
                continue  # título do bloco de resumo, logo antes de "(+) SALDO EM CONTA:"
            if linha.startswith(_FIM):
                m = _SALDO_FINAL.match(linha)
                if not m or saldo is None or _cd(valor_br(m["v"]), m["cd"]) != saldo:
                    raise LayoutInesperado(self.nome, "saldo_final_diferente_do_ultimo_saldo_do_dia", num)
                if pendente is not None:
                    raise LayoutInesperado(self.nome, "lancamento_sem_saldo_do_dia", num)
                break
            if m := _SALDO_DIA.match(linha):
                if saldo is None:
                    raise LayoutInesperado(self.nome, "saldo_do_dia_sem_saldo_anterior", num)
                self._fecha(pendente, transacoes, len(segmentos))
                pendente = None
                fechamento = _cd(valor_br(m["v"]), m["cd"])
                segmentos.append(Segmento(f"dia {len(segmentos)}", saldo, fechamento))
                saldo = fechamento
                continue
            if m := _LANCAMENTO.match(linha):
                texto, cd = m["texto"], m["cd"]
                if texto == "SALDO ANTERIOR":
                    if saldo is not None or cd == "*":
                        raise LayoutInesperado(self.nome, "saldo_anterior", num)
                    saldo = _cd(valor_br(m["v"]), cd)
                    continue
                if texto == "SALDO BLOQUEADO ANTERIOR" and cd == "*":
                    continue  # informativo, não é lançamento
                if cd == "*" or saldo is None:
                    raise LayoutInesperado(self.nome, "lancamento_inesperado", num)
                self._fecha(pendente, transacoes, len(segmentos))
                data = datetime.strptime(m["data"], "%d/%m/%Y").date()
                pendente = [num, data, texto, _cd(valor_br(m["v"]), cd), []]
                continue
            if pendente is None:
                raise LayoutInesperado(self.nome, "linha_solta", num)
            pendente[4].append(linha.strip())
        else:
            raise LayoutInesperado(self.nome, "resumo_final_ausente")

        if not transacoes:
            raise LayoutInesperado(self.nome, "arquivo_sem_lancamentos")
        return ResultadoExtracao(self.banco, self.produto, transacoes, segmentos, [titular])

    def _fecha(self, pendente: list | None, transacoes: list[TransacaoBruta], segmento: int) -> None:
        if pendente is None:
            return
        num, data, texto, valor, complemento = pendente
        transacoes.append(self._monta(num, data, texto, valor, complemento, segmento))

    def _monta(self, num: int, data: date, texto: str, valor: Decimal, complemento: list[str],
               segmento: int) -> TransacaoBruta:
        historico, contraparte = self._separa_historico(texto)
        nome = doc = revisao = ""
        if historico in _TIPOS:
            _, sinal, regra = _TIPOS[historico]
            if sinal and (valor > 0) != (sinal > 0):
                raise LayoutInesperado(self.nome, "sinal_incoerente_com_tipo", num)
            nome, doc, revisao = self._complemento(regra, complemento, num)
            nome = nome or contraparte
        return TransacaoBruta(data, historico, valor, segmento, nome, doc, num, revisao)

    def _separa_historico(self, texto: str) -> tuple[str, str]:
        """(histórico, empresa embutida) tirando o documento do começo."""
        for h in _ORDEM:
            if texto == h:
                return h, ""
            if texto.endswith(" " + h) and _DOC.match(texto[: -len(h) - 1]):
                return h, ""
        if m := _CONVENIO_EMPRESA.match(texto):
            return "DÉB.CONV.DEMAIS EMPRESAS", m["empresa"]
        primeiro, _, resto = texto.partition(" ")
        return (resto if resto and _DOC.match(primeiro) else texto), ""

    def _complemento(self, regra: str, linhas: list[str], num: int) -> tuple[str, str, str]:
        """(nome, documento, motivo de revisão) conforme a regra do tipo."""
        if regra == "nenhum":
            if linhas:
                raise LayoutInesperado(self.nome, "complemento_inesperado", num)
            return "", "", ""
        if regra == "ignora":
            return "", "", ""
        if regra == "estabelecimento":
            if len(linhas) != 1 or not linhas[0].endswith(" BRA"):
                raise LayoutInesperado(self.nome, "estabelecimento", num)
            texto = linhas[0][: -len(" BRA")]
            if "*" in texto:  # só o prefixo antes do '*' será usado; a cidade vai junto com o resto
                return texto.split("*", 1)[0] + "*", "", ""
            separado = separa_cidade(texto, largura_truncada=13)
            if separado is None:
                return "", "", "cidade_nao_identificada"
            return separado[0], "", ""
        if regra == "pix":
            # "Pagamento Pix" / documento / mensagem livre opcional (ignorada)
            if len(linhas) < 2 or linhas[0] != "Pagamento Pix":
                raise LayoutInesperado(self.nome, "pix", num)
            if _CNPJ_PIX.match(linhas[1]):
                return "", linhas[1].replace(" ", "/"), ""
            if _CPF_PIX.match(linhas[1]) and len(linhas) == 2:
                return "", linhas[1], ""
            raise LayoutInesperado(self.nome, "pix_documento", num)
        if regra in ("favorecido", "remetente"):
            prefixo = "FAV.: " if regra == "favorecido" else "REM.: "
            if not linhas or not linhas[0].startswith(prefixo):
                raise LayoutInesperado(self.nome, regra, num)
            return linhas[0][len(prefixo):].strip(), "", ""  # demais linhas: mensagem livre, ignorada
        if regra == "nome_livre":
            if not linhas:
                raise LayoutInesperado(self.nome, "nome_livre", num)
            return " ".join(linhas), "", ""
        raise AssertionError(regra)
