"""CLI.

python -m statement extrair --entrada data/raw/<pasta> --usuario u07 --saida data/saida/u07.csv
python -m statement tudo                       (every folder in data/raw -> data/saida/transacoes.csv)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import ACCEPTED, Execution, run, run_all


def _parser_args() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m statement")
    sub = ap.add_subparsers(dest="command", required=True)
    extract_cmd = sub.add_parser("extrair", help="extrai, anonimiza e grava o CSV de um usuário")
    extract_cmd.add_argument("--entrada", dest="source", type=Path, required=True, help="pasta (ou arquivo) com os extratos")
    extract_cmd.add_argument("--usuario", dest="user", required=True, help="pseudônimo uNN (ex.: u07)")
    extract_cmd.add_argument("--saida", dest="output", type=Path, required=True, help="CSV de saída")
    all_cmd = sub.add_parser("tudo", help="processa cada pasta de --raw (pasta N = usuário uNN) e junta num CSV único")
    all_cmd.add_argument("--raw", type=Path, default=Path("data/raw"), help="padrão: data/raw")
    all_cmd.add_argument("--saida", dest="output", type=Path, default=Path("data/saida/transacoes.csv"),
                    help="CSV geral (padrão: data/saida/transacoes.csv); os CSVs por usuário ficam ao lado")
    for p in (extract_cmd, all_cmd):
        p.add_argument("--privado", dest="private", type=Path, default=Path("data/privado"),
                       help="pasta de revisar.csv e historicos_desconhecidos.csv (padrão: data/privado)")
    return ap


def _print(execution: Execution, output: Path, private: Path, prefix: str = "") -> None:
    for r in execution.reports:
        period = f"{r.periodo_inicio}..{r.periodo_fim}" if r.periodo_inicio else "-"
        print(
            f"{prefix}[{r.status:9}] {r.arquivo} | parser={r.parser or '-'} | período={period} | "
            f"extraídas={r.linhas_extraidas} gravadas={r.linhas_gravadas} revisar={r.linhas_revisar} "
            f"duplicadas={r.linhas_duplicadas} omitidas={r.linhas_omitidas} | "
            f"reconciliação={r.reconciliacao} ({r.segmentos_divergentes}/{r.segmentos} divergentes)"
            + (f" | motivo={r.motivo}" if r.motivo else "")
        )
    accepted = sum(r.status == ACCEPTED for r in execution.reports)
    print(f"{prefix}{accepted} de {len(execution.reports)} arquivo(s) aceito(s); {len(execution.lines)} linha(s).")
    if execution.to_review:
        print(f"{prefix}{len(execution.to_review)} linha(s) para revisão em {private / 'revisar.csv'}")
    if execution.unknown:
        print(f"{prefix}{len(execution.unknown)} histórico(s) fora do mapa em "
              f"{private / 'historicos_desconhecidos.csv'}")
    if execution.leak is not None:
        print(f"erro: {execution.leak}. Nada foi gravado em {output}.", file=sys.stderr)
    elif accepted:
        print(f"{prefix}CSV gravado em {output}")


def main(argv: list[str] | None = None) -> int:
    args = _parser_args().parse_args(argv)
    if args.command == "extrair":
        if not args.source.exists():
            print("erro: --entrada não existe", file=sys.stderr)
            return 3
        try:
            execution = run(args.source, args.user, args.output, args.private)
        except ValueError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return 3
        _print(execution, args.output, args.private)
        return execution.exit_code

    if not args.raw.is_dir():
        print("erro: --raw não é uma pasta", file=sys.stderr)
        return 3
    try:
        overall = run_all(args.raw, args.output.parent, args.output, args.private)
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 3
    for u, execution in overall.by_user.items():
        print(f"== {u}")
        _print(execution, args.output.parent / f"{u}.csv", args.private, prefix="   ")
    if overall.leak is not None:
        print(f"erro: {overall.leak}. Nada foi gravado em {args.output}.", file=sys.stderr)
    else:
        print(f"\nCSV geral: {overall.lines} linha(s) de {len(overall.by_user)} usuário(s) em {args.output}")
        print("Para rotular (treino do ML): python -m ml.label")
    return overall.exit_code
