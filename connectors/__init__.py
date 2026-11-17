"""Fábrica de conectores. Los imports son perezosos para no cargar pandas/SQLAlchemy si no se usan."""
from __future__ import annotations

from config import AgentConfig

from .base import ConnectorError, DataConnector, InvalidRequestError, UnknownResourceError


def _connector_class(kind: str) -> type[DataConnector]:
    if kind == "sql":
        from .sql_connector import SQLConnector

        return SQLConnector
    if kind == "dbf":
        from .dbf_connector import DBFConnector

        return DBFConnector
    if kind == "excel":
        from .excel_connector import ExcelConnector

        return ExcelConnector
    raise ValueError(f"Tipo de fuente desconocido: {kind}")


def build_resources(config: AgentConfig) -> dict[str, tuple[DataConnector, str]]:
    """Devuelve {nombre_recurso: (conector, tabla)} a partir de config.yaml."""
    resources: dict[str, tuple[DataConnector, str]] = {}
    for name, source in config.sources.items():
        connector = _connector_class(source.type)(name, source, config.security)
        for table in source.tables:
            resources[table] = (connector, table)
    return resources


__all__ = [
    "ConnectorError",
    "DataConnector",
    "InvalidRequestError",
    "UnknownResourceError",
    "build_resources",
]
