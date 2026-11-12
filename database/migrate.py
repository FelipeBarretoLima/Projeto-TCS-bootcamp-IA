"""Aplica no banco as migrações de database/migrations que ainda não foram aplicadas.

    python -m database.migrate            aplica as pendentes
    python -m database.migrate --status   só lista o que já foi e o que falta

Lê a conexão de DATABASE_URL (arquivo .env na raiz). Cada arquivo .sql roda inteiro numa transação:
se der erro no meio, nada dele fica no banco. As aplicadas ficam registradas em
public.migracoes_aplicadas, então rodar de novo não repete nada. Nunca edite uma migração já
aplicada: crie a próxima (0002_..., 0003_...).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PASTA = Path(__file__).parent / "migrations"

_CRIA_REGISTRO = """
create table if not exists public.migracoes_aplicadas (
    nome       text primary key,
    aplicada_em timestamptz not null default now()
);
alter table public.migracoes_aplicadas enable row level security;
"""


def migracoes(pasta: Path = PASTA) -> list[Path]:
    """Arquivos .sql em ordem de nome (0001_..., 0002_...)."""
    return sorted(pasta.glob("*.sql"))


def url_do_banco() -> str:
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("erro: DATABASE_URL vazio. Preencha o arquivo .env na raiz do projeto.")
    return url


def aplica(conexao: psycopg.Connection, pasta: Path = PASTA) -> list[str]:
    """Aplica as pendentes, uma transação por arquivo. Devolve os nomes aplicados agora."""
    with conexao.transaction():
        conexao.execute(_CRIA_REGISTRO)
    feitas = {n for (n,) in conexao.execute("select nome from public.migracoes_aplicadas")}
    aplicadas = []
    for arquivo in migracoes(pasta):
        if arquivo.name in feitas:
            continue
        with conexao.transaction():
            conexao.execute(arquivo.read_text("utf-8"))
            conexao.execute("insert into public.migracoes_aplicadas (nome) values (%s)", (arquivo.name,))
        aplicadas.append(arquivo.name)
    return aplicadas


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m database.migrate", description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true", help="só mostra o que já foi aplicado e o que falta")
    args = ap.parse_args(argv)
    with psycopg.connect(url_do_banco(), autocommit=True) as conexao:
        if args.status:
            existe = conexao.execute("select to_regclass('public.migracoes_aplicadas')").fetchone()[0]
            feitas = {n for (n,) in conexao.execute("select nome from public.migracoes_aplicadas")} if existe else set()
            for arquivo in migracoes():
                print(f"  {'aplicada' if arquivo.name in feitas else 'PENDENTE':9} {arquivo.name}")
            return 0
        aplicadas = aplica(conexao)
    if aplicadas:
        for nome in aplicadas:
            print(f"aplicada: {nome}")
    else:
        print("nada a aplicar: o banco já está em dia")
    return 0


if __name__ == "__main__":
    sys.exit(main())
