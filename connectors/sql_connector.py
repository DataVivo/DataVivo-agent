"""Conector SQL (SQL Server, MySQL, PostgreSQL, SQLite, cualquier ODBC vía pyodbc).

Seguridad:
- Las consultas se construyen con SQLAlchemy Core: los identificadores salen de la reflexión
  del esquema filtrada por la lista blanca y los valores van siempre como bind parameters.
- Cada sentencia enviada al driver pasa por `assert_not_write_statement`.
- La sesión se marca como solo lectura cuando el motor lo permite. Aun así, la medida
  principal es que el usuario de BD del cliente tenga SOLO permisos de lectura (db_datareader).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Column, MetaData, Table, column, create_engine, event, select, text
from sqlalchemy.sql import FromClause

from config import SecurityConfig, SourceConfig
from protocol import ColumnInfo, Filter, FilterOp
from sql_guard import assert_not_write_statement

from .base import ConnectorError, DataConnector, InvalidRequestError, coerce_value

log = logging.getLogger(__name__)

_SESSION_READ_ONLY = {
    "sqlite": "PRAGMA query_only = ON",
    "postgresql": "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY",
    "mysql": "SET SESSION TRANSACTION READ ONLY",
    "mariadb": "SET SESSION TRANSACTION READ ONLY",
}


class SQLConnector(DataConnector):
    def __init__(self, name: str, source: SourceConfig, security: SecurityConfig) -> None:
        super().__init__(name, source, security)
        self.engine = create_engine(source.resolve_url(), pool_pre_ping=True, pool_recycle=1800)
        self._from_cache: dict[str, FromClause] = {}
        self._install_read_only_guards()

    def _install_read_only_guards(self) -> None:
        dialect = self.engine.dialect.name
        ro_sql = _SESSION_READ_ONLY.get(dialect)
        if ro_sql is None:
            log.warning(
                "[%s] El motor %s no admite sesión de solo lectura: usa un usuario con permisos SOLO de lectura",
                self.name, dialect,
            )

        @event.listens_for(self.engine, "connect")
        def _set_read_only(dbapi_conn, _record):  # noqa: ANN001
            if ro_sql is None:
                return
            cur = dbapi_conn.cursor()
            try:
                cur.execute(ro_sql)
            finally:
                cur.close()
            if dialect != "sqlite":
                dbapi_conn.commit()

        @event.listens_for(self.engine, "before_cursor_execute")
        def _guard(_conn, _cursor, statement, _params, _context, _many):  # noqa: ANN001
            assert_not_write_statement(statement)

    def close(self) -> None:
        self.engine.dispose()

    # ---- Esquema --------------------------------------------------------------------
    def _from(self, table: str) -> FromClause:
        with self._lock:
            cached = self._from_cache.get(table)
        if cached is not None:
            return cached
        tcfg = self._table_cfg(table)
        if tcfg.query:
            # Consulta personalizada (validada como SELECT al cargar config) usada como subconsulta
            fc = text(tcfg.query).columns(*[column(c) for c in tcfg.columns]).subquery(f"q_{table}")
        else:
            fc = Table(tcfg.table, MetaData(), schema=tcfg.schema_, autoload_with=self.engine)
        with self._lock:
            self._from_cache[table] = fc
        return fc

    def _discover_columns(self, table: str) -> list[ColumnInfo]:
        return [ColumnInfo(name=c.name, type=_type_name(c)) for c in self._from(table).c]

    # ---- Consulta -------------------------------------------------------------------
    def _fetch(
        self, table: str, columns: list[str], filters: list[Filter], limit: int, offset: int
    ) -> list[dict[str, Any]]:
        fc = self._from(table)
        tcfg = self._table_cfg(table)
        stmt = select(*[fc.c[name] for name in columns])

        for f in filters:
            col = fc.c[f.field]
            stmt = stmt.where(_condition(col, f))

        if tcfg.order_by or offset:
            order_name = tcfg.order_by or self.allowed_columns(table)[0].name
            if order_name not in fc.c:
                raise ConnectorError(f"[{table}] order_by {order_name!r} no existe")
            stmt = stmt.order_by(fc.c[order_name])

        stmt = stmt.limit(limit)
        if offset:
            stmt = stmt.offset(offset)

        # engine.connect() hace ROLLBACK al cerrar: nunca hay commit
        with self.engine.connect() as conn:
            result = conn.execute(stmt)
            return [dict(row._mapping) for row in result]


def _type_name(col: Column) -> str:
    try:
        return col.type.python_type.__name__
    except (NotImplementedError, AttributeError):
        return "unknown"


def _target_type(col: Column) -> type | None:
    try:
        return col.type.python_type
    except (NotImplementedError, AttributeError):
        return None


def _condition(col: Column, f: Filter):
    target = _target_type(col)
    if f.op is FilterOp.in_:
        return col.in_([coerce_value(v, target) for v in f.value])
    if f.op is FilterOp.like:
        return col.ilike(f.value)
    value = coerce_value(f.value, target)
    if value is None:
        return col.is_(None) if f.op is FilterOp.eq else col.is_not(None)
    ops = {
        FilterOp.eq: col.__eq__,
        FilterOp.ne: col.__ne__,
        FilterOp.gt: col.__gt__,
        FilterOp.gte: col.__ge__,
        FilterOp.lt: col.__lt__,
        FilterOp.lte: col.__le__,
    }
    try:
        return ops[f.op](value)
    except KeyError:  # pragma: no cover
        raise InvalidRequestError(f"Operador no soportado: {f.op}") from None
