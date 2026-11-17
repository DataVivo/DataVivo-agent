"""Conector Excel / CSV con pandas.

Cada hoja se carga en memoria y se cachea; se recarga automáticamente si cambia la fecha de
modificación del fichero. El filtrado se hace en Python puro (nunca DataFrame.query/eval).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from config import SecurityConfig, SourceConfig
from protocol import ColumnInfo, Filter

from .base import ConnectorError, DataConnector, scan

EXCEL_EXT = {".xlsx", ".xlsm", ".xls"}
CSV_EXT = {".csv", ".txt"}


class ExcelConnector(DataConnector):
    def __init__(self, name: str, source: SourceConfig, security: SecurityConfig) -> None:
        super().__init__(name, source, security)
        self.base = Path(source.path).resolve()
        self._data: dict[str, tuple[float, list[str], list[dict[str, Any]]]] = {}

    def _path(self, table: str) -> Path:
        path = (self.base / self._table_cfg(table).file).resolve()
        if not path.is_relative_to(self.base):
            raise ConnectorError(f"[{table}] el fichero está fuera de la carpeta base")
        if not path.is_file():
            raise ConnectorError(f"[{table}] no se encuentra el fichero")
        if path.suffix.lower() not in EXCEL_EXT | CSV_EXT:
            raise ConnectorError(f"[{table}] extensión no soportada: {path.suffix}")
        return path

    def _read(self, path: Path, table: str) -> pd.DataFrame:
        tcfg = self._table_cfg(table)
        if path.suffix.lower() in CSV_EXT:
            return pd.read_csv(
                path,
                sep=self.source.csv_sep,
                engine="python",  # necesario para autodetectar el separador
                encoding=self.source.encoding or "utf-8-sig",
            )
        return pd.read_excel(path, sheet_name=tcfg.sheet if tcfg.sheet is not None else 0, dtype=object)

    def _load(self, table: str) -> tuple[list[str], list[dict[str, Any]]]:
        path = self._path(table)
        mtime = path.stat().st_mtime
        with self._lock:
            cached = self._data.get(table)
        if cached and cached[0] == mtime:
            return cached[1], cached[2]

        df = self._read(path, table)
        df.columns = [str(c).strip() for c in df.columns]
        df = df.loc[:, [c for c in df.columns if not c.startswith("Unnamed:")]]
        df = df.dropna(how="all")
        names = list(df.columns)
        rows = [{k: _clean(v) for k, v in rec.items()} for rec in df.to_dict("records")]

        with self._lock:
            changed = cached is not None
            self._data[table] = (mtime, names, rows)
        if changed:
            self.invalidate(table)  # las columnas pueden haber cambiado
        return names, rows

    def _discover_columns(self, table: str) -> list[ColumnInfo]:
        names, rows = self._load(table)
        cols = []
        for name in names:
            sample = next((r[name] for r in rows if r.get(name) is not None), None)
            cols.append(ColumnInfo(name=name, type=type(sample).__name__ if sample is not None else "unknown"))
        return cols

    def _fetch(
        self, table: str, columns: list[str], filters: list[Filter], limit: int, offset: int
    ) -> list[dict[str, Any]]:
        _, rows = self._load(table)
        return scan(rows, columns, filters, limit, offset)


def _clean(value: Any) -> Any:
    """NaN/NaT -> None y escalares numpy -> tipos nativos de Python."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        return value.item()
    return value
