import datetime as dt
import sqlite3
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import AgentConfig  # noqa: E402


def write_dbf(path: Path, fields: list[tuple[str, str, int, int]], records: list[list], encoding="cp850", deleted=()):
    """Escribe un DBF dBase III mínimo. fields = [(nombre, tipo, longitud, decimales)]."""
    today = dt.date.today()
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(f[2] for f in fields)
    out = bytearray(struct.pack("<BBBBIHH20x", 0x03, today.year - 1900, today.month, today.day,
                                len(records), header_len, record_len))
    for name, ftype, length, dec in fields:
        out += struct.pack("<11sc4xBB14x", name.encode("ascii"), ftype.encode("ascii"), length, dec)
    out += b"\r"
    for i, rec in enumerate(records):
        out += b"*" if i in deleted else b" "
        for (name, ftype, length, dec), value in zip(fields, rec):
            if ftype == "C":
                raw = str(value).encode(encoding).ljust(length)
            elif ftype == "N":
                raw = (f"{value:.{dec}f}" if dec else str(value)).encode().rjust(length)
            elif ftype == "D":
                raw = value.strftime("%Y%m%d").encode()
            elif ftype == "L":
                raw = b"T" if value else b"F"
            out += raw[:length]
    out += b"\x1a"
    path.write_bytes(bytes(out))


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    # SQLite
    con = sqlite3.connect(tmp_path / "erp.db")
    con.executescript(
        """
        CREATE TABLE CLIENTES (CODIGO INTEGER PRIMARY KEY, NOMBRE TEXT, CIUDAD TEXT, SALDO NUMERIC(10,2),
                               FECHA_ALTA DATE, PASSWORD TEXT);
        INSERT INTO CLIENTES VALUES (1,'Ferretería López','Madrid',120.50,'2020-01-15','x'),
                                    (2,'Bodegas Ruiz','Sevilla',0,'2021-06-01','y'),
                                    (3,'Talleres Martín','Madrid',999.99,'2019-03-20','z');
        """
    )
    con.commit()
    con.close()

    # DBF
    write_dbf(
        tmp_path / "ARTICULO.DBF",
        [("CODIGO", "C", 6, 0), ("DESCRIP", "C", 30, 0), ("PVP", "N", 8, 2), ("STOCK", "N", 5, 0),
         ("ALTA", "D", 8, 0), ("ACTIVO", "L", 1, 0)],
        [
            ["A001", "Tornillo cabeza plana", 0.15, 1000, dt.date(2020, 1, 1), True],
            ["A002", "Martillo carpintería", 12.5, 3, dt.date(2021, 5, 5), True],
            ["A003", "Llave inglesa", 18.0, 0, dt.date(2022, 2, 2), False],
            ["A004", "Registro borrado", 1.0, 1, dt.date(2022, 2, 2), True],
        ],
        deleted={3},
    )

    # Excel + CSV
    import pandas as pd

    pd.DataFrame(
        {"Referencia": ["R1", "R2", "R3"], "Descripción": ["Caja", "Palé", None],
         "Unidades": [10, 0, 7], "Fecha": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"])}
    ).to_excel(tmp_path / "stock.xlsx", sheet_name="Hoja1", index=False)
    (tmp_path / "tarifas.csv").write_text("codigo;precio\nT1;10,5\nT2;20\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def config(data_dir: Path) -> AgentConfig:
    return AgentConfig.model_validate(
        {
            "cloud": {"url": "ws://localhost:8000/agent/ws", "allow_insecure": True},
            "security": {"max_limit": 50},
            "sources": {
                "erp": {
                    "type": "sql",
                    "url": f"sqlite:///{(data_dir / 'erp.db').as_posix()}",
                    "tables": {
                        "clientes": {"table": "CLIENTES", "columns": ["CODIGO", "NOMBRE", "CIUDAD", "SALDO", "FECHA_ALTA"],
                                     "order_by": "CODIGO"},
                        "madrid": {"query": "SELECT CODIGO, NOMBRE FROM CLIENTES WHERE CIUDAD = 'Madrid'",
                                   "columns": ["CODIGO", "NOMBRE"]},
                    },
                },
                "gestion": {
                    "type": "dbf",
                    "path": str(data_dir),
                    "encoding": "cp850",
                    "tables": {"articulos": {"file": "ARTICULO.DBF", "columns": "*"}},
                },
                "hojas": {
                    "type": "excel",
                    "path": str(data_dir),
                    "tables": {
                        "stock": {"file": "stock.xlsx", "sheet": "Hoja1", "columns": "*"},
                        "tarifas": {"file": "tarifas.csv", "columns": "*"},
                    },
                    "csv_sep": ";",
                },
            },
        }
    )
