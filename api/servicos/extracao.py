"""Ponte entre a API e o módulo de extração (`extrato`)."""

import tempfile
from dataclasses import asdict
from pathlib import Path

from extrato.estabelecimentos import pessoas_declaradas
from extrato.parsers.base import primeira_linha, texto_pdf
from extrato.pipeline import executa

from .. import config
from ..esquemas import Relatorio, ResultadoUpload, Transacao


class VazamentoNaSaida(Exception):
    """O validador achou possível dado pessoal: nenhuma linha pode ser devolvida."""


def processa_extrato(conteudo: bytes, extensao: str, usuario: str) -> ResultadoUpload:
    """Roda o pipeline num diretório temporário, apagado no fim. Nada fica gravado."""
    pessoas = pessoas_declaradas(config.DIR_PRIVADO)
    try:
        with tempfile.TemporaryDirectory(prefix="extrato_") as tmp:
            pasta = Path(tmp)
            # nome fixo: o nome original pode ter dado pessoal; os parsers só olham a extensão
            arquivo = pasta / f"extrato{extensao}"
            arquivo.write_bytes(conteudo)
            execucao = executa(
                arquivo, usuario, pasta / "saida.csv", pasta / "privado", pessoas=pessoas
            )
    finally:
        # os caches de leitura guardam o texto do arquivo: não manter em memória
        texto_pdf.cache_clear()
        primeira_linha.cache_clear()

    if execucao.vazamento is not None:
        raise VazamentoNaSaida(str(execucao.vazamento))

    dados = asdict(execucao.relatorios[0])
    relatorio = Relatorio(**{campo: dados[campo] for campo in Relatorio.model_fields})
    # o original (sem anonimizar) vai junto só para mostrar ao dono; ML e banco usam o anonimizado
    transacoes = [
        Transacao(**linha.model_dump(exclude={"id_usuario"}),
                  historico_original=original["historico"], contraparte_original=original["contraparte"])
        for linha, original in zip(execucao.linhas, execucao.originais, strict=True)
    ]
    return ResultadoUpload(relatorio=relatorio, transacoes=transacoes)
