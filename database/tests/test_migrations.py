"""Migrations: checked without a database (the SQL must match the Python classes)."""

import re

from api.schemas import Transaction
from database.migrate import list_migrations
from statement.models import PaymentMethod, TransactionType
from ml.classes import Category

SQL = "\n".join(m.read_text("utf-8") for m in list_migrations())


def _check_values(column: str) -> set[str]:
    m = re.search(rf"\b{column}\b[^\n]*?check \({column} in \((.*?)\)\)", SQL, re.S)
    assert m, f"check de {column} não encontrado"
    return set(re.findall(r"'([^']+)'", m.group(1)))


def test_migrations_numbered_in_order():
    names = [m.name for m in list_migrations()]
    assert names and all(re.fullmatch(r"\d{4}_[a-z0-9_]+\.sql", n) for n in names)
    assert [int(n[:4]) for n in names] == list(range(1, len(names) + 1))


def test_categories_equal_to_the_model():
    assert _check_values("categoria") == {c.value for c in Category}


def test_payment_methods_and_types_equal_to_the_parser():
    assert _check_values("meio") == {m.value for m in PaymentMethod}
    assert _check_values("tipo") == {t.value for t in TransactionType}


def test_origins_cover_the_api_ones_plus_user_correction():
    from_api = set(Transaction.model_fields["origem_categoria"].annotation.__args__[0].__args__)
    assert _check_values("origem_categoria") == from_api | {"usuario"}


def test_no_password_column():
    # the password lives in Supabase Auth; here we only look at the code, without the "--" comments
    code = re.sub(r"--[^\n]*", "", SQL)
    assert not re.search(r"senha|password", code, re.I)


def test_all_category_lists_in_the_sql_are_equal():
    """transacoes and correcoes repeat the list: both must follow ml.classes.Category."""
    lists = [set(re.findall(r"'([^']+)'", m.group(1))) for m in re.finditer(r"\bcategoria in \((.*?)\)\)", SQL, re.S)]
    assert len(lists) >= 2 and all(l == {c.value for c in Category} for l in lists)
