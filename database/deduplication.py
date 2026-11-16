"""Do not count the same transaction twice when two statements overlap.

Rule (agreed with the group): within the same user and the same bank, each transaction is
identified by (bank, date, amount, type, payment method, history, counterparty). The comparison is
by COUNT: if the database already has 2 equal rows and the new statement brings 3, only 1 goes in
(the missing one).

- Same purchase in two overlapping statements -> goes in once.
- Two genuinely equal purchases in the same statement (two R$ 8.94 rides on the same day) -> both go in.
- The same purchase in different banks -> both go in (the search is done only within the same bank).
Nothing already saved is deleted or changed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from typing import Any

Key = tuple[str, date, Decimal, str, str, str, str]


def key(t: Mapping[str, Any]) -> Key:
    return (t["banco"], t["data"], Decimal(t["valor"]).quantize(Decimal("0.01")), t["tipo"], t["meio"],
            t["historico"], t["contraparte"] or "")


def split_new_with_ids(existing: Iterable[Mapping[str, Any]], new: list[Mapping[str, Any]]):
    """Returns (the ones to be saved, the ids of the existing ones that matched the duplicates).

    The id ("id" field of each existing one) says which already saved transaction also came in this statement.
    """
    remaining: defaultdict[Key, list[Any]] = defaultdict(list)
    for t in existing:
        remaining[key(t)].append(t.get("id"))
    to_save, duplicate_ids = [], []
    for t in new:
        queue = remaining.get(key(t))
        if queue:
            duplicate_ids.append(queue.pop(0))
        else:
            to_save.append(t)
    return to_save, duplicate_ids


def split_new(existing: Iterable[Mapping[str, Any]], new: list[Mapping[str, Any]]):
    """Returns (the ones to be saved, how many were duplicates), in statement order."""
    to_save, duplicate_ids = split_new_with_ids(existing, new)
    return to_save, len(duplicate_ids)
