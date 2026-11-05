"""CLI.

python -m extrato extrair --entrada data/raw/<pasta> --usuario u07 --saida data/saida/u07.csv
python -m extrato tudo                       (todas as pastas de data/raw -> data/saida/transacoes.csv)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import ACEITO, Execucao, executa, executa_tudo


def _parser_args() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m extrato")
    sub = ap.add_subparsers(dest="comando", required=True)
    ex = sub.add_parser("extrair", help="extrai, anonimiza e grava o CSV de um usuário")
    ex.add_argument("--entrada", type=Path, required=True, help="pasta (ou arquivo) com os extratos")
    ex.add_argument("--usuario", required=True, help="pseudônimo uNN (ex.: u07)")
    ex.add_argument("--saida", type=Path, required=True, help="CSV de saída")
    tu = sub.add_parser("tudo", help="processa cada pasta de --raw (pasta N = usuário uNN) e junta num CSV único")
    tu.add_argument("--raw", type=Path, default=Path("data/raw"), help="padrão: data/raw")
    tu.add_argument("--saida", type=Path, default=Path("data/saida/transacoes.csv"),
                    help="CSV geral (padrão: data/saida/transacoes.csv); os CSVs por usuário ficam ao lado")
    for p in (ex, tu):
        p.add_argument("--privado", type=Path, default=Path("data/privado"),
                       help="pasta de revisar.csv e historicos_desconhecidos.csv (padrão: data/privado)")
    return ap


def _imprime(execucao: Execucao, saida: Path, privado: Path, prefixo: str = "") -> None:
    for r in execucao.relatorios:
        periodo = f"{r.periodo_inicio}..{r.periodo_fim}" if r.periodo_inicio else "-"
        print(
            f"{prefixo}[{r.status:9}] {r.arquivo} | parser={r.parser or '-'} | período={periodo} | "
            f"extraídas={r.linhas_extraidas} gravadas={r.linhas_gravadas} revisar={r.linhas_revisar} "
            f"duplicadas={r.linhas_duplicadas} omitidas={r.linhas_omitidas} | "
            f"reconciliação={r.reconciliacao} ({r.segmentos_divergentes}/{r.segmentos} divergentes)"
            + (f" | motivo={r.motivo}" if r.motivo else "")
        )
    aceitos = sum(r.status == ACEITO for r in execucao.relatorios)
    print(f"{prefixo}{aceitos} de {len(execucao.relatorios)} arquivo(s) aceito(s); {len(execucao.linhas)} linha(s).")
    if execucao.revisar:
        print(f"{prefixo}{len(execucao.revisar)} linha(s) para revisão em {privado / 'revisar.csv'}")
    if execucao.desconhecidos:
        print(f"{prefixo}{len(execucao.desconhecidos)} histórico(s) fora do mapa em "
              f"{privado / 'historicos_desconhecidos.csv'}")
    if execucao.vazamento is not None:
        print(f"erro: {execucao.vazamento}. Nada foi gravado em {saida}.", file=sys.stderr)
    elif aceitos:
        print(f"{prefixo}CSV gravado em {saida}")


def main(argv: list[str] | None = None) -> int:
    args = _parser_args().parse_args(argv)
    if args.comando == "extrair":
        if not args.entrada.exists():
            print("erro: --entrada não existe", file=sys.stderr)
            return 3
        try:
            execucao = executa(args.entrada, args.usuario, args.saida, args.privado)
        except ValueError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return 3
        _imprime(execucao, args.saida, args.privado)
        return execucao.codigo_saida

    if not args.raw.is_dir():
        print("erro: --raw não é uma pasta", file=sys.stderr)
        return 3
    try:
        geral = executa_tudo(args.raw, args.saida.parent, args.saida, args.privado)
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 3
    for u, execucao in geral.por_usuario.items():
        print(f"== {u}")
        _imprime(execucao, args.saida.parent / f"{u}.csv", args.privado, prefixo="   ")
    if geral.vazamento is not None:
        print(f"erro: {geral.vazamento}. Nada foi gravado em {args.saida}.", file=sys.stderr)
    else:
        print(f"\nCSV geral: {geral.linhas} linha(s) de {len(geral.por_usuario)} usuário(s) em {args.saida}")
        print("Para rotular (treino do ML): python -m ml.rotular")
    return geral.codigo_saida
