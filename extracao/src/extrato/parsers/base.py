"""Interface que todo parser de formato implementa.

Cada formato (banco + produto + extensão) tem um parser próprio e determinístico.
Nada aqui é heurística genérica: o parser só aceita o que conhece e falha no resto.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal

from ..modelos import Meio


class ErroExtracao(Exception):
    """Base dos erros do pipeline. A mensagem nunca carrega conteúdo do extrato."""


class FormatoNaoReconhecido(ErroExtracao):
    pass


class FormatoAmbiguo(ErroExtracao):
    pass


class LayoutInesperado(ErroExtracao):
    """Algo no arquivo fora do layout que o parser conhece. Só código + página."""

    def __init__(self, parser: str, motivo: str, pagina: int | None = None):
        onde = f" (página {pagina})" if pagina is not None else ""
        super().__init__(f"parser {parser}: {motivo}{onde}")
        self.motivo = motivo
        self.pagina = pagina


class HistoricoDesconhecido(ErroExtracao):
    def __init__(self, parser: str, historico: str):
        # o histórico fica no atributo (vai para data/privado), não na mensagem
        super().__init__(f"parser {parser}: histórico fora do mapa explícito")
        self.parser = parser
        self.historico = historico


@dataclass(frozen=True)
class TransacaoBruta:
    """Lançamento como lido do documento. Vive só em memória.

    historico: o texto do tipo de lançamento (ex.: "PIX ENVIADO"), sem o complemento.
    contraparte: nome do favorecido/pagador/estabelecimento, se o layout informar.
    documento_contraparte: CPF/CNPJ da contraparte como aparece (mascarado ou não), se houver.
    segmento: índice (ou índices) em ResultadoExtracao.segmentos usados na reconciliação.
      Uma transação pode entrar em vários: ex. o total do dia e o saldo do extrato.
    pagina: só para mensagens de erro (nunca o conteúdo).
    """

    data: date
    historico: str
    valor: Decimal
    segmento: int | tuple[int, ...]
    contraparte: str = ""
    documento_contraparte: str = ""
    pagina: int | None = None
    # preenchido pelo parser quando ele mesmo não consegue garantir a anonimização
    # (ex.: cidade não identificada no nome do estabelecimento): a linha vai para revisão
    motivo_revisao: str = ""
    # cópia de um lançamento que o documento repete (ex.: dia de fronteira entre extratos
    # mesclados): entra na reconciliação do seu trecho, mas não vai para o CSV
    duplicada: bool = False
    # lançamento que não é movimento novo do usuário (ex.: na fatura, o pagamento da fatura,
    # que já está no extrato da conta, e o saldo restante da fatura anterior): entra na
    # reconciliação, mas não vai para o CSV
    omitida: bool = False


@dataclass(frozen=True)
class Segmento:
    """Trecho do documento com totais declarados: abertura + soma(valores) == fechamento.

    Exemplos:
      conta corrente: abertura = saldo anterior, fechamento = saldo final (ou saldo do dia);
      fatura: abertura = -saldo da fatura anterior (0 se não houver),
              fechamento = -total da fatura (dívida é negativa).
    """

    rotulo: str  # sem dado pessoal, ex.: "fatura 2025-03" ou "dia 2024-01-05"
    abertura: Decimal
    fechamento: Decimal
    # documento independente dentro do arquivo (ex.: "fatura 2026-08-10" num PDF com várias
    # faturas). Só é usado por parsers com REJEITA_POR_DOCUMENTO.
    documento: str = ""


@dataclass
class ResultadoExtracao:
    banco: str
    produto: Literal["conta", "cartao"]
    transacoes: list[TransacaoBruta]
    segmentos: list[Segmento]
    nomes_titulares: list[str] = field(default_factory=list)  # titular + portadores/adicionais


class Parser(ABC):
    """Contrato de um parser de formato."""

    nome: ClassVar[str]  # ex.: "bradesco_conta_pdf"
    banco: ClassVar[str]  # slug do contrato de saída
    produto: ClassVar[Literal["conta", "cartao"]]
    # Mapa explícito histórico normalizado -> meio. Fora do mapa = erro.
    MEIOS: ClassVar[Mapping[str, Meio]]
    # True só para formatos que comprovadamente não trazem saldo/total nenhum
    # (ex.: CSV exportado pela Nubank). O arquivo é aceito com reconciliação "sem_totais".
    SEM_TOTAIS: ClassVar[bool] = False
    # True para arquivos que juntam documentos independentes (ex.: várias faturas mescladas):
    # um documento que não fecha é rejeitado sozinho (suas linhas saem) e o resto segue.
    # Todo segmento precisa ter `documento`. Decisão do usuário em 2026-11-04.
    REJEITA_POR_DOCUMENTO: ClassVar[bool] = False

    @classmethod
    @abstractmethod
    def detecta(cls, caminho: Path) -> bool:
        """True se o arquivo tem a assinatura deste formato. Não pode lançar exceção."""

    @abstractmethod
    def extrai(self, caminho: Path) -> ResultadoExtracao:
        """Lê o arquivo inteiro. Qualquer coisa fora do layout esperado é erro."""

    @classmethod
    def meio_de(cls, historico_normalizado: str) -> Meio:
        try:
            return cls.MEIOS[historico_normalizado]
        except KeyError:
            raise HistoricoDesconhecido(cls.nome, historico_normalizado) from None


# --- utilitários de leitura para `detecta` (cache: vários parsers olham o mesmo arquivo) ---

@lru_cache(maxsize=32)
def texto_pdf(caminho: Path, max_paginas: int | None = None) -> tuple[str, ...]:
    """Texto de cada página (pdfplumber). Tupla vazia se o arquivo não for PDF legível."""
    import pdfplumber

    try:
        with pdfplumber.open(caminho) as pdf:
            paginas = pdf.pages if max_paginas is None else pdf.pages[:max_paginas]
            return tuple(p.extract_text() or "" for p in paginas)
    except Exception:  # noqa: BLE001 - detecta() não pode falhar
        return ()


@lru_cache(maxsize=32)
def primeira_linha(caminho: Path, encoding: str = "utf-8-sig") -> str:
    """Primeira linha do arquivo de texto ('' se não der para ler)."""
    try:
        with open(caminho, encoding=encoding, newline="") as f:
            return f.readline().rstrip("\r\n")
    except (OSError, UnicodeDecodeError):
        return ""
