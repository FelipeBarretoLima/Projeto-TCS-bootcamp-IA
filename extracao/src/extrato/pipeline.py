"""arquivo -> parser -> reconciliação -> normalização -> anonimização -> validação -> CSV."""

from __future__ import annotations

import csv
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from pydantic import ValidationError

from . import estabelecimentos, padroes
from .anonimizacao import Revisar, resolve_contraparte
from .modelos import LinhaSaida, Tipo
from .normalizacao import normaliza_historico
from .parsers.base import (
    ErroExtracao, HistoricoDesconhecido, LayoutInesperado, Parser, ResultadoExtracao,
)
from .parsers.registro import escolhe_parser
from .reconciliacao import confere, reconcilia, separa_documentos_divergentes
from .validacao import VazamentoDetectado, grava_csv

ACEITO, REJEITADO = "aceito", "rejeitado"


@dataclass
class RelatorioArquivo:
    """Uma linha do relatório. Só contagens e códigos: nada do conteúdo do extrato."""

    arquivo: str
    parser: str = ""
    periodo_inicio: str = ""
    periodo_fim: str = ""
    linhas_extraidas: int = 0
    linhas_gravadas: int = 0
    linhas_revisar: int = 0
    linhas_duplicadas: int = 0
    linhas_omitidas: int = 0
    documentos_rejeitados: int = 0
    historicos_desconhecidos: int = 0
    segmentos: int = 0
    segmentos_divergentes: int = 0
    reconciliacao: str = "nao_executada"
    status: str = REJEITADO
    motivo: str = ""


@dataclass
class _Extraido:
    caminho: Path
    relatorio: RelatorioArquivo
    parser: Parser | None = None
    resultado: ResultadoExtracao | None = None


@dataclass
class Execucao:
    relatorios: list[RelatorioArquivo]
    linhas: list[LinhaSaida] = field(default_factory=list)
    revisar: list[dict[str, str]] = field(default_factory=list)
    desconhecidos: list[dict[str, str]] = field(default_factory=list)
    nomes_titulares: list[str] = field(default_factory=list)
    vazamento: VazamentoDetectado | None = None

    @property
    def codigo_saida(self) -> int:
        if self.vazamento is not None:
            return 2
        return 0 if all(r.status == ACEITO for r in self.relatorios) else 1


def _arquivos(entrada: Path) -> list[Path]:
    if entrada.is_file():
        return [entrada]
    return sorted(
        p for p in entrada.rglob("*")
        if p.is_file() and not any(parte.startswith(".") for parte in p.relative_to(entrada).parts)
    )


def _extrai(caminho: Path, rotulo: str, parsers: Sequence[type[Parser]] | None) -> _Extraido:
    item = _Extraido(caminho, RelatorioArquivo(arquivo=rotulo))
    rel = item.relatorio
    try:
        parser = escolhe_parser(caminho, parsers)
        rel.parser = parser.nome
        resultado = parser.extrai(caminho)
    except LayoutInesperado as exc:
        rel.motivo = f"LayoutInesperado:{exc.motivo}" + (f"@p{exc.pagina}" if exc.pagina else "")
        return item
    except ErroExtracao as exc:
        rel.motivo = type(exc).__name__
        return item
    except Exception as exc:  # noqa: BLE001 - mensagem de exceção pode conter conteúdo
        rel.motivo = f"erro_no_parser:{type(exc).__name__}"
        return item

    rel.linhas_extraidas = len(resultado.transacoes)
    if resultado.transacoes:
        datas = sorted(t.data for t in resultado.transacoes)
        rel.periodo_inicio, rel.periodo_fim = datas[0].isoformat(), datas[-1].isoformat()
    if parser.SEM_TOTAIS:
        if resultado.segmentos:
            rel.motivo = "segmentos_em_formato_sem_totais"
            return item
        rel.reconciliacao = "sem_totais"
        item.parser, item.resultado = parser, resultado
        return item
    status = confere(resultado)
    rel.segmentos, rel.segmentos_divergentes = status.segmentos, status.divergentes
    rejeitados: list[str] = []
    try:
        if parser.REJEITA_POR_DOCUMENTO:
            resultado, rejeitados = separa_documentos_divergentes(resultado)
        reconcilia(resultado)
    except ErroExtracao as exc:
        rel.reconciliacao, rel.motivo = "falhou", type(exc).__name__
        return item
    rel.reconciliacao = "ok"
    if rejeitados:
        # rótulos de documento são só tipo + data (ex.: "fatura 2026-08-10"): sem dado pessoal
        rel.reconciliacao = "ok_com_documentos_rejeitados"
        rel.documentos_rejeitados = len(rejeitados)
        rel.motivo = "documentos_rejeitados:" + ";".join(rejeitados)
    item.parser, item.resultado = parser, resultado
    return item


def _transforma(item: _Extraido, usuario: str, nomes: re.Pattern[str] | None, execucao: Execucao,
                pessoas: frozenset[str] = frozenset()) -> None:
    assert item.parser is not None and item.resultado is not None
    rel, parser, resultado = item.relatorio, item.parser, item.resultado
    linhas: list[LinhaSaida] = []
    revisar: list[dict[str, str]] = []
    desconhecidos: set[str] = set()
    invalidas = 0

    duplicadas = sum(t.duplicada for t in resultado.transacoes)
    omitidas = sum(t.omitida and not t.duplicada for t in resultado.transacoes)
    for t in resultado.transacoes:
        if t.duplicada or t.omitida:
            continue
        # mesma forma das chaves dos mapas (normaliza_historico); padroes.remove só apaga dado pessoal
        historico = normaliza_historico(padroes.remove(t.historico, nomes))
        try:
            meio = parser.meio_de(historico)
        except HistoricoDesconhecido as exc:
            desconhecidos.add(exc.historico)
            continue
        contraparte = (Revisar(t.motivo_revisao) if t.motivo_revisao
                       else resolve_contraparte(t.contraparte, t.documento_contraparte, meio, nomes))
        if isinstance(contraparte, Revisar):
            revisar.append({
                "id_usuario": usuario, "arquivo": rel.arquivo, "data": t.data.isoformat(),
                "historico": historico, "contraparte_original": t.contraparte,
                "valor": f"{t.valor:.2f}", "motivo": contraparte.motivo,
            })
            continue
        # nome-base do estabelecimento e pessoa física na maquininha -> PESSOA_FISICA
        contraparte = estabelecimentos.padroniza(contraparte, meio, pessoas)
        try:
            linhas.append(LinhaSaida(
                id_usuario=usuario, data=t.data, historico=historico, contraparte=contraparte,
                valor=t.valor, tipo=Tipo.ENTRADA if t.valor > 0 else Tipo.SAIDA,
                meio=meio, banco=resultado.banco,
            ))
        except ValidationError:  # a mensagem do pydantic inclui o valor: não propagar
            invalidas += 1

    rel.historicos_desconhecidos = len(desconhecidos)
    execucao.desconhecidos.extend(
        {"id_usuario": usuario, "parser": parser.nome, "historico": h} for h in sorted(desconhecidos)
    )
    if desconhecidos:
        rel.motivo = "HistoricoDesconhecido"
        return
    if invalidas:
        rel.motivo = f"linhas_invalidas:{invalidas}"
        return
    rel.linhas_gravadas, rel.linhas_revisar, rel.linhas_duplicadas = len(linhas), len(revisar), duplicadas
    rel.linhas_omitidas = omitidas
    rel.status = ACEITO
    execucao.linhas.extend(linhas)
    execucao.revisar.extend(revisar)


def executa(
    entrada: Path,
    usuario: str,
    saida: Path,
    dir_privado: Path,
    parsers: Sequence[type[Parser]] | None = None,
    pessoas: frozenset[str] | None = None,
) -> Execucao:
    """`pessoas`: nomes marcados como pessoa. None = lê os mapas de `dir_privado`."""
    if not re.fullmatch(r"u\d{2}", usuario):
        raise ValueError("--usuario deve ser 'u' + 2 dígitos (ex.: u07)")
    return _finaliza(_extrai_pasta(entrada, parsers), usuario, saida, dir_privado, pessoas=pessoas)


def _extrai_pasta(entrada: Path, parsers: Sequence[type[Parser]] | None) -> list[_Extraido]:
    """Fase 1: extrair e reconciliar todos os arquivos da pasta."""
    return [
        _extrai(p, p.relative_to(entrada).as_posix() if entrada.is_dir() else p.name, parsers)
        for p in _arquivos(entrada)
    ]


def _titulares(extraidos: list[_Extraido]) -> set[str]:
    return {n for e in extraidos if e.resultado for n in e.resultado.nomes_titulares}


def _finaliza(
    extraidos: list[_Extraido],
    usuario: str,
    saida: Path,
    dir_privado: Path,
    outros_titulares: set[str] = frozenset(),
    pessoas: frozenset[str] | None = None,
) -> Execucao:
    """Fases 2 e 3: anonimizar (com os titulares desta pasta + os de outras) e gravar."""
    execucao = Execucao(relatorios=[e.relatorio for e in extraidos])
    execucao.nomes_titulares = sorted(_titulares(extraidos))
    nomes_titulares = sorted(_titulares(extraidos) | set(outros_titulares))
    nomes = padroes.regex_de_nomes(nomes_titulares)

    # fase 2: normalizar e anonimizar (pessoas marcadas pelo usuário nos mapas de data/privado)
    pessoas = estabelecimentos.pessoas_declaradas(dir_privado) if pessoas is None else pessoas
    for item in extraidos:
        if item.resultado is not None:
            _transforma(item, usuario, nomes, execucao, pessoas)

    _grava_privado(dir_privado / "revisar.csv", usuario, execucao.revisar)
    _grava_privado(dir_privado / "historicos_desconhecidos.csv", usuario, execucao.desconhecidos)

    # fase 3: validar e gravar (só se algum arquivo foi aceito)
    if any(r.status == ACEITO for r in execucao.relatorios):
        try:
            grava_csv(execucao.linhas, saida, nomes_titulares)
        except VazamentoDetectado as exc:
            execucao.vazamento = exc
    _grava_relatorio(saida.with_name(saida.stem + ".relatorio.csv"), execucao.relatorios)
    return execucao


@dataclass
class ExecucaoGeral:
    """Todas as pastas de data/raw/: um CSV por usuário + o CSV geral."""

    por_usuario: dict[str, Execucao]
    linhas: int = 0
    vazamento: VazamentoDetectado | None = None

    @property
    def codigo_saida(self) -> int:
        if self.vazamento is not None or any(e.vazamento for e in self.por_usuario.values()):
            return 2
        return max((e.codigo_saida for e in self.por_usuario.values()), default=0)


def usuario_da_pasta(pasta: Path) -> str:
    """data/raw/7 -> u07. Pasta que não for um número é erro (não dá para adivinhar o pseudônimo)."""
    if not re.fullmatch(r"\d{1,2}", pasta.name):
        raise ValueError(f"pasta de usuário deve ser um número de 1 ou 2 dígitos: {pasta.name!r}")
    return f"u{int(pasta.name):02d}"


def executa_tudo(
    raiz: Path,
    dir_saida: Path,
    saida_geral: Path,
    dir_privado: Path,
    parsers: Sequence[type[Parser]] | None = None,
) -> ExecucaoGeral:
    """Processa cada subpasta de `raiz` como um usuário e junta tudo num CSV único.

    O CSV geral passa de novo pelo validador, agora com os nomes de titular de todas as
    pastas: o titular de um usuário pode aparecer como contraparte no extrato de outro.
    """
    pastas = [p for p in raiz.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if not pastas:
        raise ValueError("nenhuma pasta de usuário em --raw")
    # 1º extrai todas as pastas: o titular de um usuário pode ser contraparte de outro
    extraidos = {usuario_da_pasta(p): _extrai_pasta(p, parsers) for p in sorted(pastas, key=usuario_da_pasta)}
    todos = set().union(*(_titulares(e) for e in extraidos.values()))
    pessoas = estabelecimentos.pessoas_declaradas(dir_privado)
    por_usuario: dict[str, Execucao] = {
        u: _finaliza(ext, u, dir_saida / f"{u}.csv", dir_privado, todos, pessoas) for u, ext in extraidos.items()
    }
    geral = ExecucaoGeral(por_usuario)
    linhas = [l for e in por_usuario.values() if e.vazamento is None for l in e.linhas]
    nomes = sorted({n for e in por_usuario.values() for n in e.nomes_titulares})
    try:
        grava_csv(linhas, saida_geral, nomes)
        geral.linhas = len(linhas)
    except VazamentoDetectado as exc:
        geral.vazamento = exc
    return geral


def _grava_privado(caminho: Path, usuario: str, novas: list[dict[str, str]]) -> None:
    """Substitui as linhas deste usuário e preserva as dos outros."""
    existentes: list[dict[str, str]] = []
    if caminho.exists():
        with open(caminho, encoding="utf-8", newline="") as f:
            existentes = [r for r in csv.DictReader(f) if r.get("id_usuario") != usuario]
    todas = existentes + novas
    if not todas:
        caminho.unlink(missing_ok=True)
        return
    caminho.parent.mkdir(parents=True, exist_ok=True)
    colunas = list(dict.fromkeys(k for r in todas for k in r))
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=colunas, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(todas)


def _grava_relatorio(caminho: Path, relatorios: list[RelatorioArquivo]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=[c.name for c in fields(RelatorioArquivo)], lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(asdict(r) for r in relatorios)
