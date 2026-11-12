"""Training labeling: the parser's CSV + a `categoria` column (rules + merchant map).

    python -m ml.label
        [--entrada data/saida/transacoes.csv] [--saida ml/dados/transacoes_rotuladas.csv]
        [--privado data/privado]

Input: exactly the parser's CSV (8-column contract). Output: the same columns, in the same
order and with the same values, plus `categoria` at the end. Nothing else changes: at inference,
the parser delivers the same CSV without the category and the classifier adds the column.

Merchant map (data/privado, outside git — it has real names), maintained by the user:
    estabelecimentos_revisar.csv   first map (priority)
    estabelecimentos_novos.csv     extended on each labeling with what is not mapped yet
    In both, a blank class = accepts the suggested class (user decision on 2026-11-04).
The map is matched by the merchant base name (the same one the parser writes in the counterparty).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from statement.merchants import base_name, looks_like_person
from statement.models import COLUMNS, INDIVIDUAL_PERSON, PaymentMethod, TransactionType
from statement.normalization import strip_accents

from .classes import Category, by_rule

REVIEWED_FILE = "estabelecimentos_revisar.csv"
NEW_FILE = "estabelecimentos_novos.csv"
MAP_COLUMNS = ["contraparte", "linhas", "classe_sugerida", "regra_achou_classe", "nome_canonico_sugerido",
                "parece_pessoa", "classe", "nome_canonico", "e_pessoa"]
LABELED_COLUMNS = (*COLUMNS, "categoria")


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_map(private_dir: Path) -> dict[str, Category]:
    """merchant base name -> class. An invalid class is an error (fix it in the spreadsheet).

    If two map rows fall on the same base name with different classes, the one from the reviewed
    file wins and, within the same file, the one with more occurrences.
    """
    name_map: dict[str, Category] = {}
    weight: dict[str, tuple[int, int]] = {}
    for priority, map_file in enumerate((REVIEWED_FILE, NEW_FILE)):
        for n, r in enumerate(_read(private_dir / map_file), start=2):
            class_name = (r.get("classe") or "").strip() or r.get("classe_sugerida", "")
            if not class_name:
                continue
            if class_name not in Category.__members__.values():
                raise ValueError(f"{map_file}, linha {n}: classe inválida (use uma das 8 classes)")
            keys = {base_name(r["contraparte"])}
            if (r.get("nome_canonico") or "").strip():
                keys.add(base_name(r["nome_canonico"]))
            p = (-priority, int(r.get("linhas") or 0))
            for k in keys:
                if k and (k not in weight or p > weight[k]):
                    name_map[k], weight[k] = Category(class_name), p
    return name_map


def category_for(row: dict[str, str], name_map: dict[str, Category]) -> Category | None:
    rule = by_rule(PaymentMethod(row["meio"]), TransactionType(row["tipo"]), row["historico"], row["contraparte"])
    # the map is indexed by base name (PIX to a company arrives without the card standardization)
    return rule if rule is not None else name_map.get(base_name(row["contraparte"]))


# --- suggestions for what is not in the map yet ---

_CLASS_RULES = [
    (Category.EATING_OUT, r"\bIFD\b|IFOOD|LANCH|RESTAUR|PIZZ|BURG|FOODS?\b|\bBAR\b|BEER|CAFE|SORVET|CHURRAS|"
                                 r"ACAI|PASTEL|SUSHI|OUTBACK|MC ?DONALD|\bBK\b|SUBWAY|ESPETO|CHOPP|BISTRO|COZINHA"),
    (Category.GROCERIES, r"SUPER|MERCAD|SACOLAO|ASSAI|ATACAD|HORTI|PADARIA|PANIF|ACOUGUE|EMPORIO|"
                        r"BEBID|CONVENIENC|FRUT|QUITANDA|ARMAZEM"),
    (Category.TRANSPORT, r"UBER|\b99\b|POSTO|COMBUST|PEDAGIO|SEM PARAR|ESTACION|AUTO ?PECAS|PNEU|MECANIC"),
    (Category.BILLS_SERVICES, r"TOTALPASS|NETFLIX|SPOTIFY|BYTEDANCE|GOOGLE|APPLE|PRIME|DISNEY|YOUTUBE|DEEZER|"
                                r"OPENAI|MICROSOFT|FARMA|DROGA|RAIA|PACHECO|CLINIC|ODONTO|HOSPITAL|LABORAT|"
                                r"CLARO|VIVO|\bTIM\b|\bOI\b|ENERGIA|SANEAMENTO|ACADEMIA|SMART ?FIT"),
    (Category.SHOPPING, r"SHOPEE|SHPP|MERCADO ?LIVRE|AMAZON|MAGAZINE|MAGALU|AMERICANAS|ALIEXPRESS|SHEIN|RENNER|"
                        r"RIACHUELO|\bC ?& ?A\b|LOJA|MODAS?|CALCAD|ELETRO|PAPELAR"),
]


def suggest_class(contraparte: str) -> Category | None:
    c = strip_accents(contraparte).upper()
    return next((k for k, rx in _CLASS_RULES if re.search(rx, c)), None)


def update_new(private_dir: Path, uncategorized: Iterable[str]) -> int:
    """Appends to estabelecimentos_novos.csv what is not in any map yet.

    Never deletes or changes existing rows (the user may be filling them in). Returns how many were added.
    """
    path = private_dir / NEW_FILE
    already = {base_name(r["contraparte"]) for fname in (REVIEWED_FILE, NEW_FILE) for r in _read(private_dir / fname)}
    counts = Counter(c for c in uncategorized if c and c != INDIVIDUAL_PERSON and base_name(c) not in already)
    if not counts:
        return 0
    new_rows = []
    for c, n in counts.most_common():
        sugg = suggest_class(c)
        new_rows.append({"contraparte": c, "linhas": str(n), "classe_sugerida": sugg.value if sugg else "compras",
                      "regra_achou_classe": "sim" if sugg else "não (padrão: compras)",
                      "nome_canonico_sugerido": c, "parece_pessoa": "sim" if looks_like_person(c) else "",
                      "classe": "", "nome_canonico": "", "e_pessoa": ""})
    already_exists = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MAP_COLUMNS, lineterminator="\n")
        if not already_exists:
            w.writeheader()
        w.writerows(new_rows)
    return len(new_rows)


# --- labeling ---

@dataclass
class LabelResult:
    rows: int = 0
    by_category: Counter[str] = field(default_factory=Counter)
    new_in_map: int = 0


def label_csv(source: Path, output: Path, private_dir: Path) -> LabelResult:
    with open(source, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError("a entrada não está no contrato do parser (cabeçalho diferente)")
        rows = list(reader)
    name_map = load_map(private_dir)
    res = LabelResult(rows=len(rows))
    missing: list[str] = []
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    with open(temp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(LABELED_COLUMNS)
        for l in rows:
            c = category_for(l, name_map)
            if c is None:
                missing.append(l["contraparte"])
            res.by_category[c.value if c else "(sem categoria)"] += 1
            w.writerow([*(l[k] for k in COLUMNS), c.value if c else ""])
    temp.replace(output)
    res.new_in_map = update_new(private_dir, missing)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ml.label", description="rotula o CSV do parser para o treino")
    ap.add_argument("--entrada", dest="source", type=Path, default=Path("data/saida/transacoes.csv"))
    ap.add_argument("--saida", dest="output", type=Path, default=Path("ml/dados/transacoes_rotuladas.csv"))
    ap.add_argument("--privado", dest="private", type=Path, default=Path("data/privado"))
    args = ap.parse_args(argv)
    try:
        res = label_csv(args.source, args.output, args.private)
    except (OSError, ValueError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 3
    print(f"{res.rows} linha(s) rotuladas em {args.output}")
    for k, v in res.by_category.most_common():
        print(f"  {k:22} {v:6}  {100 * v / max(res.rows, 1):5.1f}%")
    if res.new_in_map:
        print(f"{res.new_in_map} estabelecimento(s) novo(s) em {args.private / NEW_FILE} "
              "(classe em branco = aceita a sugerida)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
