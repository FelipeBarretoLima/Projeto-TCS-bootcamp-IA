"""Ponte entre a API e o módulo de extração (`extrato`)."""

import tempfile
from dataclasses import asdict
from pathlib import Path

from statement.merchants import declared_people
from statement.parsers.base import first_line, pdf_text
from statement.pipeline import run

from .. import config
from ..schemas import Relatorio, ResultadoUpload, Transacao


class VazamentoNaSaida(Exception):
    """O validador achou possível dado pessoal: nenhuma linha pode ser devolvida."""


def processa_extrato(conteudo: bytes, extensao: str, usuario: str) -> ResultadoUpload:
    """Roda o pipeline num diretório temporário, apagado no fim. Nada fica gravado."""
    pessoas = declared_people(config.DIR_PRIVADO)
    try:
        with tempfile.TemporaryDirectory(prefix="extrato_") as tmp:
            pasta = Path(tmp)
            # nome fixo: o nome original pode ter dado pessoal; os parsers só olham a extensão
            arquivo = pasta / f"extrato{extensao}"
            arquivo.write_bytes(conteudo)
            execucao = run(
                arquivo, usuario, pasta / "saida.csv", pasta / "privado", people=pessoas
            )
    finally:
        # os caches de leitura guardam o texto do arquivo: não manter em memória
        pdf_text.cache_clear()
        first_line.cache_clear()

    if execucao.leak is not None:
        raise VazamentoNaSaida(str(execucao.leak))

    dados = asdict(execucao.reports[0])
    relatorio = Relatorio(**{campo: dados[campo] for campo in Relatorio.model_fields})
    # o original (sem anonimizar) vai junto só para mostrar ao dono; ML e banco usam o anonimizado
    transacoes = [
        Transacao(**linha.model_dump(exclude={"id_usuario"}),
                  historico_original=original["historico"], contraparte_original=original["contraparte"])
        for linha, original in zip(execucao.lines, execucao.originals, strict=True)
    ]
    return ResultadoUpload(relatorio=relatorio, transacoes=transacoes)
