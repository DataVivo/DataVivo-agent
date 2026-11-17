"""Guardas de solo lectura para SQL.

Dos niveles:
- `assert_read_only_query`: estricto. Para consultas SQL personalizadas definidas en config.yaml.
  Solo SELECT/WITH, una única sentencia, ninguna palabra clave de escritura/DDL.
- `assert_not_write_statement`: se ejecuta sobre CADA sentencia que SQLAlchemy envía al driver
  (incluida la reflexión de metadatos) y rechaza las que empiezan por un verbo de escritura.
"""
from __future__ import annotations

import re

WRITE_KEYWORDS = frozenset(
    {
        # REPLACE no se incluye (es también una función de texto); "REPLACE INTO" se bloquea por INTO
        "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT", "DROP", "ALTER", "CREATE",
        "TRUNCATE", "RENAME", "GRANT", "REVOKE", "DENY", "EXEC", "EXECUTE", "CALL", "ATTACH",
        "DETACH", "VACUUM", "REINDEX", "COPY", "LOAD", "INTO", "BACKUP", "RESTORE", "SHUTDOWN",
        "DBCC", "OPENROWSET", "OPENDATASOURCE", "XP_CMDSHELL", "LOCK", "HANDLER",
    }
)

_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_STRING_RE = re.compile(r"'(?:[^']|'')*'")
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ReadOnlyViolation(ValueError):
    pass


def _strip(sql: str) -> str:
    sql = _COMMENT_RE.sub(" ", sql)
    return _STRING_RE.sub("''", sql)  # literales no cuentan como palabras clave


def assert_read_only_query(sql: str) -> None:
    cleaned = _strip(sql).strip().rstrip(";").strip()
    if not cleaned:
        raise ReadOnlyViolation("Consulta vacía")
    if ";" in cleaned:
        raise ReadOnlyViolation("Solo se permite una sentencia")
    words = [w.upper() for w in _WORD_RE.findall(cleaned)]
    if words[0] not in ("SELECT", "WITH"):
        raise ReadOnlyViolation("La consulta debe empezar por SELECT o WITH")
    forbidden = WRITE_KEYWORDS.intersection(words)
    if forbidden:
        raise ReadOnlyViolation(f"Palabras clave no permitidas: {', '.join(sorted(forbidden))}")


def assert_not_write_statement(sql: str) -> None:
    words = _WORD_RE.findall(_strip(sql))
    if words and words[0].upper() in WRITE_KEYWORDS:
        raise ReadOnlyViolation(f"Sentencia bloqueada en modo solo lectura: {words[0].upper()}")
