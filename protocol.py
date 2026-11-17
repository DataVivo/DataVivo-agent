"""Mensajes del túnel agente <-> nube. Mantener sincronizado con cloud-api/protocol.py."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

PROTOCOL_VERSION = 1


class FilterOp(str, Enum):
    eq = "eq"
    ne = "ne"
    gt = "gt"
    gte = "gte"
    lt = "lt"
    lte = "lte"
    like = "like"  # comodín %, sin distinguir mayúsculas
    in_ = "in"


class Filter(BaseModel):
    field: str = Field(max_length=128)
    op: FilterOp = FilterOp.eq
    value: Any


class ColumnInfo(BaseModel):
    name: str
    type: str


class ResourceSchema(BaseModel):
    name: str
    columns: list[ColumnInfo]


# --- Agente -> Nube ---------------------------------------------------------
class AgentHello(BaseModel):
    type: Literal["hello"] = "hello"
    protocol: int = PROTOCOL_VERSION
    agent_version: str
    resources: list[ResourceSchema]


class AgentResult(BaseModel):
    type: Literal["result"] = "result"
    id: str
    ok: bool
    rows: list[dict[str, Any]] | None = None
    error_code: str | None = None
    error_message: str | None = None


# --- Nube -> Agente ---------------------------------------------------------
class QueryRequest(BaseModel):
    type: Literal["query"] = "query"
    id: str
    resource: str = Field(max_length=128)
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    fields: list[str] | None = Field(default=None, max_length=200)
    limit: int = Field(default=100, ge=1)
    offset: int = Field(default=0, ge=0)


class ErrorCode:
    UNKNOWN_RESOURCE = "unknown_resource"
    INVALID_REQUEST = "invalid_request"
    SOURCE_ERROR = "source_error"
    TIMEOUT = "timeout"
