"""Clase base de los conectores unificados.

Todas las validaciones de seguridad comunes (lista blanca de columnas, operadores, límites)
viven aquí, de modo que ningún conector concreto puede saltárselas: los conectores solo
implementan `_discover_columns` y `_fetch`, y reciben datos ya validados y canónicos.
"""
from __future__ import annotations

import datetime as dt
import re
import threading
from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from typing import Any

from config import SecurityConfig, SourceConfig, TableConfig
from protocol import ColumnInfo, Filter, FilterOp
from serialization import row_to_jsonable

MAX_IN_VALUES = 100
MAX_VALUE_LENGTH = 500


class ConnectorError(Exception):
    """Error con mensaje seguro para enviar a la nube."""


class UnknownResourceError(ConnectorError):
    pass


class InvalidRequestError(ConnectorError):
    pass


class DataConnector(ABC):
    def __init__(self, name: str, source: SourceConfig, security: SecurityConfig) -> None:
        self.name = name
        self.source = source
        self.security = security
        self._columns_cache: dict[str, list[ColumnInfo]] = {}
        self._lock = threading.Lock()

    # ---- A implementar por cada conector --------------------------------------------
    @abstractmethod
    def _discover_columns(self, table: str) -> list[ColumnInfo]:
        """Columnas físicas del origen (todas, sin filtrar por la lista blanca)."""

    @abstractmethod
    def _fetch(
        self, table: str, columns: list[str], filters: list[Filter], limit: int, offset: int
    ) -> list[dict[str, Any]]:
        """Devuelve filas. `columns` y `filters[].field` ya están validados y en forma canónica."""

    def close(self) -> None:  # pragma: no cover - opcional
        pass

    # ---- API pública ----------------------------------------------------------------
    @property
    def tables(self) -> list[str]:
        return list(self.source.tables)

    def get_schema(self) -> dict[str, list[ColumnInfo]]:
        """Esquema expuesto (solo columnas permitidas) de cada tabla de esta fuente."""
        return {t: self.allowed_columns(t) for t in self.tables}

    def query_data(
        self,
        table: str,
        filters: list[Filter] | None = None,
        limit: int = 100,
        offset: int = 0,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        tcfg = self._table_cfg(table)
        allowed = self.allowed_columns(table)
        lookup = {c.name.lower(): c.name for c in allowed}

        if fields:
            columns = [self._resolve(f, lookup) for f in fields]
        else:
            columns = [c.name for c in allowed]

        clean_filters = [self._validate_filter(f, lookup) for f in (filters or [])]

        max_limit = min(tcfg.max_limit or self.security.max_limit, self.security.max_limit)
        limit = max(1, min(int(limit), max_limit))
        offset = max(0, int(offset))

        rows = self._fetch(table, columns, clean_filters, limit, offset)
        return [row_to_jsonable(r, self.security.decimal_mode) for r in rows]

    # ---- Helpers --------------------------------------------------------------------
    def _table_cfg(self, table: str) -> TableConfig:
        tcfg = self.source.tables.get(table)
        if tcfg is None:
            raise UnknownResourceError(f"Recurso desconocido: {table}")
        return tcfg

    def invalidate(self, table: str) -> None:
        with self._lock:
            self._columns_cache.pop(table, None)

    def allowed_columns(self, table: str) -> list[ColumnInfo]:
        tcfg = self._table_cfg(table)
        with self._lock:
            cached = self._columns_cache.get(table)
        if cached is not None:
            return cached

        physical = self._discover_columns(table)
        if tcfg.columns == "*":
            allowed = physical
        else:
            by_lower = {c.name.lower(): c for c in physical}
            allowed = []
            for name in tcfg.columns:
                col = by_lower.get(name.lower())
                if col is None:
                    raise ConnectorError(f"[{table}] la columna configurada {name!r} no existe en el origen")
                allowed.append(col)
        with self._lock:
            self._columns_cache[table] = allowed
        return allowed

    @staticmethod
    def _resolve(name: str, lookup: dict[str, str]) -> str:
        canonical = lookup.get(str(name).lower())
        if canonical is None:
            raise InvalidRequestError(f"Columna no permitida: {name}")
        return canonical

    def _validate_filter(self, f: Filter, lookup: dict[str, str]) -> Filter:
        field = self._resolve(f.field, lookup)
        value = f.value
        if f.op is FilterOp.in_:
            if not isinstance(value, list):
                raise InvalidRequestError("El operador 'in' requiere una lista")
            if not 1 <= len(value) <= MAX_IN_VALUES:
                raise InvalidRequestError(f"'in' admite entre 1 y {MAX_IN_VALUES} valores")
            for v in value:
                _check_scalar(v)
        else:
            _check_scalar(value)
            if f.op is FilterOp.like and not isinstance(value, str):
                raise InvalidRequestError("'like' requiere un texto")
            if value is None and f.op not in (FilterOp.eq, FilterOp.ne):
                raise InvalidRequestError("null solo se admite con eq / ne")
        return Filter(field=field, op=f.op, value=value)


def _check_scalar(value: Any) -> None:
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise InvalidRequestError("Los valores de filtro deben ser escalares")
    if isinstance(value, str) and len(value) > MAX_VALUE_LENGTH:
        raise InvalidRequestError("Valor de filtro demasiado largo")


# ---- Coerción de tipos y filtrado en memoria (DBF / Excel) --------------------------
_TRUE = {"1", "true", "t", "si", "sí", "s", "yes", "y"}
_FALSE = {"0", "false", "f", "no", "n"}


def coerce_value(value: Any, target: type | None) -> Any:
    """Convierte un valor de filtro (normalmente texto de la query string) al tipo de la columna."""
    if value is None or target is None or isinstance(value, target):
        return value
    try:
        if target is bool:
            s = str(value).strip().lower()
            if s in _TRUE:
                return True
            if s in _FALSE:
                return False
            raise ValueError
        if target is int:
            return int(value) if not isinstance(value, float) else value
        if target is float:
            return float(value)
        if target is Decimal:
            return Decimal(str(value))
        if issubclass(target, dt.datetime):
            return dt.datetime.fromisoformat(str(value))
        if issubclass(target, dt.date):
            return dt.date.fromisoformat(str(value)[:10])
        if target is str:
            return str(value)
    except (ValueError, TypeError, InvalidOperation):
        raise InvalidRequestError(f"Valor {value!r} no compatible con el tipo de la columna") from None
    return value


def like_to_regex(pattern: str) -> re.Pattern[str]:
    parts = [".*" if ch == "%" else "." if ch == "_" else re.escape(ch) for ch in pattern]
    return re.compile("".join(parts), re.IGNORECASE | re.DOTALL)


def _python_type(sample: Any) -> type | None:
    if sample is None:
        return None
    if isinstance(sample, bool):
        return bool
    if isinstance(sample, dt.datetime):
        return dt.datetime
    if isinstance(sample, int):
        # Un filtro "12.5" contra una columna entera debe compararse como float
        return float
    return type(sample)


def row_matches(row: dict[str, Any], filters: list[Filter], regex_cache: dict[str, re.Pattern[str]]) -> bool:
    for f in filters:
        actual = row.get(f.field)
        if f.op is FilterOp.like:
            if actual is None:
                return False
            rx = regex_cache.get(f.value) or regex_cache.setdefault(f.value, like_to_regex(f.value))
            if not rx.fullmatch(str(actual)):
                return False
            continue

        target = _python_type(actual)
        try:
            if f.op is FilterOp.in_:
                if actual not in [coerce_value(v, target) for v in f.value]:
                    return False
                continue
            expected = coerce_value(f.value, target)
            if f.op is FilterOp.eq:
                ok = actual == expected
            elif f.op is FilterOp.ne:
                ok = actual != expected
            elif actual is None:
                ok = False
            elif f.op is FilterOp.gt:
                ok = actual > expected
            elif f.op is FilterOp.gte:
                ok = actual >= expected
            elif f.op is FilterOp.lt:
                ok = actual < expected
            elif f.op is FilterOp.lte:
                ok = actual <= expected
            else:  # pragma: no cover
                ok = False
        except InvalidRequestError:
            ok = False  # el valor no es comparable con el de esta fila
        except TypeError:
            ok = False
        if not ok:
            return False
    return True


def scan(
    rows, columns: list[str], filters: list[Filter], limit: int, offset: int
) -> list[dict[str, Any]]:
    """Recorre un iterable de filas aplicando filtros, offset y límite sin cargarlo entero."""
    out: list[dict[str, Any]] = []
    skipped = 0
    cache: dict[str, re.Pattern[str]] = {}
    for row in rows:
        if filters and not row_matches(row, filters, cache):
            continue
        if skipped < offset:
            skipped += 1
            continue
        out.append({c: row.get(c) for c in columns})
        if len(out) >= limit:
            break
    return out
