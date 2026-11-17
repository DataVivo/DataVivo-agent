"""Convierte valores de cualquier origen (SQL, DBF, pandas) a JSON limpio."""
from __future__ import annotations

import base64
import datetime as dt
import math
import uuid
from decimal import Decimal
from typing import Any, Literal

DecimalMode = Literal["string", "float"]


def to_jsonable(value: Any, decimal_mode: DecimalMode = "string") -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return str(value) if decimal_mode == "string" else float(value)
    # datetime es subclase de date: comprobarlo primero
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, dict):
        return {str(k): to_jsonable(v, decimal_mode) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v, decimal_mode) for v in value]

    # Tipos de pandas / numpy sin importarlos explícitamente
    type_name = type(value).__name__
    if type_name in ("NaTType", "NAType"):
        return None
    if type_name == "Timestamp":
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar
        return to_jsonable(value.item(), decimal_mode)

    return str(value)


def row_to_jsonable(row: dict[str, Any], decimal_mode: DecimalMode = "string") -> dict[str, Any]:
    return {str(k): to_jsonable(v, decimal_mode) for k, v in row.items()}
