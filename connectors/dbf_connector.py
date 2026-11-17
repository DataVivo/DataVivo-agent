"""Conector DBF (dBase, FoxPro, Clipper) con dbfread.

dbfread es de solo lectura por diseño. Los ficheros se leen en streaming (load=False), por lo que
cada consulta recorre el fichero hasta reunir `offset + limit` filas que cumplan los filtros.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from dbfread import DBF

from config import SecurityConfig, SourceConfig
from protocol import ColumnInfo, Filter

from .base import ConnectorError, DataConnector, scan

DBF_TYPES = {
    "C": "str", "M": "str", "N": "float", "F": "float", "I": "int", "B": "float",
    "Y": "Decimal", "D": "date", "T": "datetime", "@": "datetime", "L": "bool",
    "+": "int", "O": "float", "V": "str", "G": "bytes", "P": "bytes",
}


class DBFConnector(DataConnector):
    def __init__(self, name: str, source: SourceConfig, security: SecurityConfig) -> None:
        super().__init__(name, source, security)
        self.base = Path(source.path).resolve()

    def _path(self, table: str) -> Path:
        path = (self.base / self._table_cfg(table).file).resolve()
        if not path.is_relative_to(self.base):
            raise ConnectorError(f"[{table}] el fichero está fuera de la carpeta base")
        if not path.is_file():
            raise ConnectorError(f"[{table}] no se encuentra el fichero DBF")
        return path

    def _open(self, table: str) -> DBF:
        return DBF(
            str(self._path(table)),
            encoding=self.source.encoding,  # None => codepage de la cabecera
            char_decode_errors="replace",
            ignore_missing_memofile=True,
            load=False,
        )

    def _discover_columns(self, table: str) -> list[ColumnInfo]:
        dbf = self._open(table)
        return [
            ColumnInfo(name=f.name, type=DBF_TYPES.get(f.type, f.type))
            for f in dbf.fields
            if f.type != "0"  # _NullFlags interno de Visual FoxPro
        ]

    def _fetch(
        self, table: str, columns: list[str], filters: list[Filter], limit: int, offset: int
    ) -> list[dict[str, Any]]:
        # Los registros marcados como borrados se omiten automáticamente
        return scan(iter(self._open(table)), columns, filters, limit, offset)
