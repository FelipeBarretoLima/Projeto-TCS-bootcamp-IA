"""Conta Inter: extrato em PDF.

Página 1:
    Gerado em: DD/MM/AAAA - HHhMM
    NOME DO TITULAR
    CPF/CNPJ: …, Instituição: Banco Inter, Agência: …, Conta: …
    Período: DD/MM/AAAA a DD/MM/AAAA
    Saldo total Saldo disponível: Saldo bloqueado:
    R$ X R$ Y R$ Z
    (bloqueado + disponível)
Corpo (todas as páginas): "D de Mês de AAAA Saldo do dia: R$ X" e lançamentos
    Tipo: "complemento" ±R$ valor R$ saldo_após
O complemento entre aspas pode continuar na linha seguinte. Rodapé: "Fale com a gente" e "SAC: …".

Reconciliação: cada lançamento é um segmento (saldo anterior + valor == saldo após).
O saldo de abertura do 1º lançamento não é impresso: é derivado dele mesmo, então o 1º
valor é conferido só pelas checagens de layout: "Saldo do dia" == saldo do último lançamento
do dia e "Saldo total" do resumo == saldo do último lançamento.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..modelos import Meio
from ..normalizacao import normaliza_historico, valor_br
from .base import LayoutInesperado, Parser, ResultadoExtracao, Segmento, TransacaoBruta, texto_pdf

_MESES = {m: i for i, m in enumerate(
    "Janeiro Fevereiro Março Abril Maio Junho Julho Agosto Setembro Outubro Novembro Dezembro".split(), start=1)}
_V = r"-?R\$ -?\d{1,3}(?:\.\d{3})*,\d{2}"
_CAB = [
    re.compile(r"^\S+ em: \d{2}/\d{2}/\d{4} - \d{2}h\d{2}$"),
    None,  # nome do titular
    re.compile(r"^CPF/CNPJ: .+, Instituição: Banco Inter, Agência: [\d-]+, Conta: [\d-]+$"),
    re.compile(r"^Período: \d{2}/\d{2}/\d{4} a \d{2}/\d{2}/\d{4}$"),
    re.compile(r"^Saldo total Saldo disponível: Saldo bloqueado:$"),
    re.compile(rf"^(?P<total>{_V}) (?P<disp>{_V}) (?P<bloq>{_V})$"),
    re.compile(r"^\(bloqueado \+ disponível\)$"),
]
_DIA = re.compile(rf"^(?P<d>\d{{1,2}}) de (?P<m>{'|'.join(_MESES)}) de (?P<a>\d{{4}}) "
                  rf"Saldo do dia: (?P<s>{_V})(?: Valor Saldo por transação)?$")
_TIPOS: dict[str, tuple[Meio, int, bool]] = {  # tipo -> (meio, sinal, tem contraparte)
    "Pix enviado": (Meio.PIX, -1, True),
    "Pix recebido": (Meio.PIX, +1, True),
    "Pix enviado devolvido": (Meio.ESTORNO, +1, True),
    "Pix recebido devolvido": (Meio.ESTORNO, -1, True),
    "Resgate": (Meio.INVESTIMENTO, +1, False),
    "Aplicacao": (Meio.INVESTIMENTO, -1, False),
}
_LANCAMENTO = re.compile(rf'^(?P<tipo>[^:"]+): (?P<q>".*?) (?P<v>{_V}) (?P<s>{_V})$')
_RODAPE = re.compile(r"^(?:Fale com a gente|SAC: .*Ouvidoria: .*)$")
# conteúdo entre aspas
_PIX_ISPB = re.compile(r"^Cp :\d{8}-(?P<nome>.+)$")
_PIX_AG_CONTA = re.compile(r"^\d{5} \d{8,9} (?P<nome>.+)$")
_INVESTIMENTO = re.compile(r"^CDB POS DI LIQ\. BANCO INTER S ?A$")


class InterContaPdf(Parser):
    nome = "inter_conta_pdf"
    banco = "inter"
    produto = "conta"
    MEIOS = {normaliza_historico(k): v[0] for k, v in _TIPOS.items()}

    @classmethod
    def detecta(cls, caminho: Path) -> bool:
        if caminho.suffix.lower() != ".pdf":
            return False
        paginas = texto_pdf(caminho, 1)
        return bool(paginas) and cls._cabecalho(paginas[0].splitlines()) is not None

    @staticmethod
    def _cabecalho(linhas: list[str]) -> re.Match[str] | None:
        if len(linhas) <= len(_CAB) or not all(rx is None or rx.match(l) for rx, l in zip(_CAB, linhas)):
            return None
        return _CAB[5].match(linhas[5])

    def extrai(self, caminho: Path) -> ResultadoExtracao:
        paginas = texto_pdf(caminho)
        primeira = paginas[0].splitlines()
        resumo = self._cabecalho(primeira)
        if resumo is None:
            raise LayoutInesperado(self.nome, "cabecalho", 1)
        titular = primeira[1].strip()
        corpo = [(1, l) for l in primeira[len(_CAB):]]
        corpo += [(n, l) for n, p in enumerate(paginas[1:], start=2) for l in p.splitlines()]

        transacoes: list[TransacaoBruta] = []
        segmentos: list[Segmento] = []
        dia: date | None = None
        saldo_dia: Decimal | None = None
        saldo: Decimal | None = None
        pendente: list | None = None  # [pagina, data, tipo, aspas, valor] com aspas ainda abertas

        def confere_dia(num: int) -> None:
            if saldo_dia is not None and saldo != saldo_dia:
                raise LayoutInesperado(self.nome, "saldo_do_dia_diferente_do_ultimo_lancamento", num)

        for num, linha in corpo:
            if pendente is not None:  # complemento entre aspas continua nesta linha
                if not linha.endswith('"') or '"' in linha[:-1]:
                    raise LayoutInesperado(self.nome, "aspas_nao_fechadas", num)
                pendente[3] += " " + linha
                transacoes.append(self._monta(*pendente, len(segmentos) - 1))
                pendente = None
                continue
            if _RODAPE.match(linha):
                continue
            if m := _DIA.match(linha):
                confere_dia(num)
                dia = date(int(m["a"]), _MESES[m["m"]], int(m["d"]))
                saldo_dia = valor_br(m["s"])
                continue
            if m := _LANCAMENTO.match(linha):
                if dia is None:
                    raise LayoutInesperado(self.nome, "lancamento_sem_dia", num)
                valor, apos = valor_br(m["v"]), valor_br(m["s"])
                segmentos.append(Segmento(f"lançamento {len(segmentos)}",
                                          apos - valor if saldo is None else saldo, apos))
                saldo = apos
                item = [num, dia, m["tipo"], m["q"], valor]
                if m["q"].count('"') == 1:
                    pendente = item
                else:
                    transacoes.append(self._monta(*item, len(segmentos) - 1))
                continue
            raise LayoutInesperado(self.nome, "linha_desconhecida", num)
        if pendente is not None:
            raise LayoutInesperado(self.nome, "aspas_nao_fechadas", len(paginas))
        confere_dia(len(paginas))
        if not transacoes:
            raise LayoutInesperado(self.nome, "arquivo_sem_lancamentos")
        if valor_br(resumo["total"]) != saldo:
            raise LayoutInesperado(self.nome, "saldo_total_diferente_do_ultimo_lancamento", 1)
        return ResultadoExtracao(self.banco, self.produto, transacoes, segmentos, [titular])

    def _monta(self, num: int, dia: date, tipo: str, aspas: str, valor: Decimal, segmento: int) -> TransacaoBruta:
        if not (aspas.startswith('"') and aspas.endswith('"') and aspas.count('"') == 2):
            raise LayoutInesperado(self.nome, "complemento_sem_aspas", num)
        conteudo = aspas[1:-1].strip()
        if tipo not in _TIPOS:
            return TransacaoBruta(dia, tipo, valor, segmento, pagina=num)  # mapa rejeita depois
        _, sinal, tem_contraparte = _TIPOS[tipo]
        if (valor > 0) != (sinal > 0):
            raise LayoutInesperado(self.nome, "sinal_incoerente_com_tipo", num)
        if not tem_contraparte:
            if not _INVESTIMENTO.match(conteudo):
                raise LayoutInesperado(self.nome, "produto_de_investimento", num)
            return TransacaoBruta(dia, tipo, valor, segmento, pagina=num)
        m = _PIX_ISPB.match(conteudo) or _PIX_AG_CONTA.match(conteudo)
        if not m:
            raise LayoutInesperado(self.nome, "complemento_pix", num)
        return TransacaoBruta(dia, tipo, valor, segmento, m["nome"].strip(), pagina=num)
