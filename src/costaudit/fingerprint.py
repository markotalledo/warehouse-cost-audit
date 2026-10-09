"""Group queries that differ only in literals: same shape, same fingerprint."""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache

import sqlglot
from sqlglot import exp

_WS = re.compile(r"\s+")
_LITERAL = re.compile(r"'(?:[^']|'')*'|\b\d+(?:\.\d+)?\b")


def normalize(sql: str) -> str:
    try:
        tree = sqlglot.parse_one(sql)
        for literal in list(tree.find_all(exp.Literal)):
            literal.replace(exp.Placeholder())
        return tree.sql(pretty=False).lower()
    except Exception:  # dialect features sqlglot cannot parse: fall back to regex
        return _WS.sub(" ", _LITERAL.sub("?", sql)).strip().lower()


@lru_cache(maxsize=200_000)  # every detector groups the same queries
def fingerprint(sql: str) -> str:
    return hashlib.sha1(normalize(sql).encode()).hexdigest()[:10]
