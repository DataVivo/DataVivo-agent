"""Carga y valida config.yaml. Es la ÚNICA fuente de nombres de tablas/columnas/ficheros."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sql_guard import assert_read_only_query

RESOURCE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TableConfig(_Strict):
    # SQL: tabla física (+ esquema) o consulta SELECT personalizada
    table: str | None = None
    schema_: str | None = Field(default=None, alias="schema")
    query: str | None = None
    # DBF / Excel / CSV: fichero relativo a source.path
    file: str | None = None
    # Excel: hoja (nombre o índice)
    sheet: str | int | None = None
    # Lista blanca de columnas. "*" = todas (no permitido en consultas personalizadas)
    columns: list[str] | Literal["*"]
    order_by: str | None = None
    max_limit: int | None = Field(default=None, ge=1)


class SourceConfig(_Strict):
    type: Literal["sql", "dbf", "excel"]
    url: str | None = None  # SQL: preferir url_file/url_env para no dejar credenciales en este fichero
    url_env: str | None = None
    url_file: str | None = None  # fichero con la cadena de conexión (protegido con ACL por el instalador)
    path: str | None = None  # DBF/Excel: carpeta base
    encoding: str | None = None  # DBF: si se omite se usa el codepage de la cabecera
    csv_sep: str | None = None  # CSV: si se omite se autodetecta
    tables: dict[str, TableConfig]

    @model_validator(mode="after")
    def _check(self) -> "SourceConfig":
        if self.type == "sql":
            if not (self.url or self.url_env or self.url_file):
                raise ValueError("Fuente SQL requiere 'url', 'url_file' o 'url_env'")
            for name, t in self.tables.items():
                if bool(t.table) == bool(t.query):
                    raise ValueError(f"[{name}] define exactamente uno de 'table' o 'query'")
                if t.query:
                    assert_read_only_query(t.query)
                    if t.columns == "*":
                        raise ValueError(f"[{name}] las consultas personalizadas requieren lista de columnas")
        else:
            if not self.path:
                raise ValueError(f"Fuente {self.type} requiere 'path'")
            for name, t in self.tables.items():
                if not t.file:
                    raise ValueError(f"[{name}] requiere 'file'")
        return self

    def resolve_url(self) -> str:
        if self.url:
            return self.url
        if self.url_file:
            return Path(self.url_file).read_text(encoding="utf-8").strip()
        value = os.environ.get(self.url_env or "")
        if not value:
            raise ValueError(f"Variable de entorno {self.url_env} no definida")
        return value


class CloudConfig(_Strict):
    url: str
    token_env: str = "DATAVIVO_AGENT_TOKEN"
    token_file: str | None = None
    allow_insecure: bool = False  # permite ws:// (solo desarrollo)
    request_timeout: float = 25.0
    max_concurrency: int = Field(default=4, ge=1, le=64)

    @model_validator(mode="after")
    def _check_scheme(self) -> "CloudConfig":
        if self.url.startswith("ws://") and not self.allow_insecure:
            raise ValueError("cloud.url usa ws:// sin cifrar; usa wss:// o allow_insecure: true en desarrollo")
        if not self.url.startswith(("ws://", "wss://")):
            raise ValueError("cloud.url debe empezar por wss://")
        return self

    def resolve_token(self) -> str:
        token = os.environ.get(self.token_env, "").strip()
        if not token and self.token_file:
            token = Path(self.token_file).read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError(f"No hay token de agente: define {self.token_env} o cloud.token_file")
        return token


class SecurityConfig(_Strict):
    allow_writes: bool = False
    max_limit: int = Field(default=1000, ge=1, le=50_000)
    decimal_mode: Literal["string", "float"] = "string"

    @field_validator("allow_writes")
    @classmethod
    def _no_writes(cls, v: bool) -> bool:
        if v:
            raise ValueError("La escritura no está implementada en esta versión del agente")
        return v


class AgentConfig(_Strict):
    cloud: CloudConfig
    security: SecurityConfig = SecurityConfig()
    sources: dict[str, SourceConfig]

    @model_validator(mode="after")
    def _unique_resources(self) -> "AgentConfig":
        seen: dict[str, str] = {}
        for src_name, src in self.sources.items():
            for res in src.tables:
                if not RESOURCE_NAME_RE.match(res):
                    raise ValueError(f"Nombre de recurso inválido: {res!r} (usa letras, números, _ o -)")
                if res in seen:
                    raise ValueError(f"Recurso {res!r} duplicado en fuentes {seen[res]!r} y {src_name!r}")
                seen[res] = src_name
        return self


def load_config(path: str | Path) -> AgentConfig:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return AgentConfig.model_validate(raw)
