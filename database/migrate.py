"""Aplica no banco as migrações de database/migrations que ainda não foram aplicadas.

    python -m database.migrate            aplica as pendentes
    python -m database.migrate --status   só lista o que já foi e o que falta

Reads the connection from DATABASE_URL (.env file at the root). Each .sql file runs whole inside one
transaction: if it fails halfway, nothing of it stays in the database. Applied ones are recorded in
public.migracoes_aplicadas, so running again repeats nothing. Never edit an already applied
migration: create the next one (0002_..., 0003_...).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_CREATE_REGISTRY = """
create table if not exists public.migracoes_aplicadas (
    nome       text primary key,
    aplicada_em timestamptz not null default now()
);
alter table public.migracoes_aplicadas enable row level security;
"""


def list_migrations(folder: Path = MIGRATIONS_DIR) -> list[Path]:
    """.sql files in name order (0001_..., 0002_...)."""
    return sorted(folder.glob("*.sql"))


def database_url() -> str:
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("erro: DATABASE_URL vazio. Preencha o arquivo .env na raiz do projeto.")
    return url


def apply(connection: psycopg.Connection, folder: Path = MIGRATIONS_DIR) -> list[str]:
    """Applies the pending ones, one transaction per file. Returns the names applied now."""
    with connection.transaction():
        connection.execute(_CREATE_REGISTRY)
    done = {n for (n,) in connection.execute("select nome from public.migracoes_aplicadas")}
    applied = []
    for file in list_migrations(folder):
        if file.name in done:
            continue
        with connection.transaction():
            connection.execute(file.read_text("utf-8"))
            connection.execute("insert into public.migracoes_aplicadas (nome) values (%s)", (file.name,))
        applied.append(file.name)
    return applied


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m database.migrate", description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true", help="só mostra o que já foi aplicado e o que falta")
    args = ap.parse_args(argv)
    with psycopg.connect(database_url(), autocommit=True) as connection:
        if args.status:
            exists = connection.execute("select to_regclass('public.migracoes_aplicadas')").fetchone()[0]
            done = {n for (n,) in connection.execute("select nome from public.migracoes_aplicadas")} if exists else set()
            for file in list_migrations():
                print(f"  {'aplicada' if file.name in done else 'PENDENTE':9} {file.name}")
            return 0
        applied = apply(connection)
    if applied:
        for name in applied:
            print(f"aplicada: {name}")
    else:
        print("nada a aplicar: o banco já está em dia")
    return 0


if __name__ == "__main__":
    sys.exit(main())
