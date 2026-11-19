"""Agente local de DataVivo.

Abre UNA conexión saliente WSS hacia la nube (no requiere abrir puertos), se autentica con su
token y atiende peticiones de consulta contra los recursos declarados en config.yaml.

Uso:
    python agent.py --config config.yaml           # ejecutar
    python agent.py --config config.yaml --check   # validar config y mostrar el catálogo
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import random
import sys
from pathlib import Path

from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from config import AgentConfig, load_config
from connectors import ConnectorError, DataConnector, InvalidRequestError, UnknownResourceError, build_resources
from protocol import AgentHello, AgentResult, ErrorCode, QueryRequest, ResourceSchema

AGENT_VERSION = "0.2.1"
DATA_DIR = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "DataVivo"
MAX_INBOUND_MESSAGE = 1 * 1024 * 1024  # la nube solo envía peticiones pequeñas
MAX_BACKOFF = 60.0

log = logging.getLogger("datavivo.agent")


class Agent:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.resources: dict[str, tuple[DataConnector, str]] = build_resources(config)
        self._semaphore = asyncio.Semaphore(config.cloud.max_concurrency)
        self._tasks: set[asyncio.Task] = set()

    # ---- Catálogo -------------------------------------------------------------------
    def catalog(self) -> list[ResourceSchema]:
        out = []
        for name, (connector, table) in self.resources.items():
            try:
                columns = connector.allowed_columns(table)
            except Exception:
                log.exception("No se pudo leer el esquema de %s; se anuncia sin columnas", name)
                columns = []
            out.append(ResourceSchema(name=name, columns=columns))
        return out

    # ---- Atención de peticiones -----------------------------------------------------
    async def handle(self, raw: str | bytes) -> AgentResult | None:
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            log.warning("Mensaje no JSON descartado")
            return None
        if not isinstance(payload, dict) or payload.get("type") != "query":
            log.warning("Tipo de mensaje no soportado: %r", payload.get("type") if isinstance(payload, dict) else None)
            return None

        request_id = str(payload.get("id", ""))[:64]
        try:
            req = QueryRequest.model_validate(payload)
        except ValidationError as exc:
            return _error(request_id, ErrorCode.INVALID_REQUEST, f"Petición inválida: {exc.error_count()} errores")

        entry = self.resources.get(req.resource)
        if entry is None:
            return _error(req.id, ErrorCode.UNKNOWN_RESOURCE, f"Recurso desconocido: {req.resource}")
        connector, table = entry

        try:
            async with self._semaphore:
                rows = await asyncio.wait_for(
                    asyncio.to_thread(connector.query_data, table, req.filters, req.limit, req.offset, req.fields),
                    timeout=self.config.cloud.request_timeout,
                )
        except (InvalidRequestError, UnknownResourceError) as exc:
            code = ErrorCode.UNKNOWN_RESOURCE if isinstance(exc, UnknownResourceError) else ErrorCode.INVALID_REQUEST
            return _error(req.id, code, str(exc))
        except TimeoutError:
            log.warning("[%s] Timeout consultando %s", req.id, req.resource)
            return _error(req.id, ErrorCode.TIMEOUT, "El origen de datos tardó demasiado")
        except ConnectorError as exc:
            log.error("[%s] Error de configuración en %s: %s", req.id, req.resource, exc)
            return _error(req.id, ErrorCode.SOURCE_ERROR, "Error en el origen de datos")
        except Exception:
            # Nunca se envían detalles internos (rutas, SQL, credenciales) a la nube
            log.exception("[%s] Error consultando %s", req.id, req.resource)
            return _error(req.id, ErrorCode.SOURCE_ERROR, "Error en el origen de datos")

        log.info("[%s] %s -> %d filas", req.id, req.resource, len(rows))
        return AgentResult(id=req.id, ok=True, rows=rows)

    async def _process(self, ws: ClientConnection, raw: str | bytes) -> None:
        result = await self.handle(raw)
        if result is not None:
            try:
                await ws.send(result.model_dump_json())
            except ConnectionClosed:
                log.warning("[%s] Conexión cerrada antes de enviar la respuesta", result.id)

    # ---- Bucle de conexión ----------------------------------------------------------
    async def run_forever(self) -> None:
        token = self.config.cloud.resolve_token()
        headers = {"Authorization": f"Bearer {token}"}
        backoff = 1.0

        while True:
            try:
                async with connect(
                    self.config.cloud.url,
                    additional_headers=headers,
                    user_agent_header=f"DataVivoAgent/{AGENT_VERSION}",
                    max_size=MAX_INBOUND_MESSAGE,
                    open_timeout=15,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    log.info("Conectado a %s", self.config.cloud.url)
                    hello = AgentHello(agent_version=AGENT_VERSION, resources=await asyncio.to_thread(self.catalog))
                    await ws.send(hello.model_dump_json())
                    backoff = 1.0
                    async for raw in ws:
                        task = asyncio.create_task(self._process(ws, raw))
                        self._tasks.add(task)
                        task.add_done_callback(self._tasks.discard)
            except InvalidStatus as exc:
                status = exc.response.status_code
                if status in (401, 403):
                    log.error("La nube rechazó el token del agente (HTTP %s). Revisa el token.", status)
                    backoff = MAX_BACKOFF
                else:
                    log.warning("Handshake rechazado (HTTP %s)", status)
            except ConnectionClosed as exc:
                log.warning("Conexión cerrada (code=%s)", exc.rcvd.code if exc.rcvd else None)
            except (OSError, TimeoutError) as exc:
                log.warning("No se pudo conectar: %s", exc.__class__.__name__)

            delay = backoff + random.uniform(0, backoff / 2)
            log.info("Reintentando en %.1fs", delay)
            await asyncio.sleep(delay)
            backoff = min(backoff * 2, MAX_BACKOFF)


def _error(request_id: str, code: str, message: str) -> AgentResult:
    return AgentResult(id=request_id, ok=False, error_code=code, error_message=message)


def _default_config() -> str:
    """config.yaml junto al ejecutable/script o, si no existe, en C:/ProgramData/DataVivo."""
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    local = base / "config.yaml"
    return str(local if local.exists() else DATA_DIR / "config.yaml")


def _setup_logging(level: str, log_file: str | None) -> None:
    # Consolas Windows (cp1252/cp850): un carácter no representable no debe romper el log
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3,
                                                             encoding="utf-8"))
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DataVivo agente local")
    parser.add_argument("--config", default=_default_config())
    parser.add_argument("--check", action="store_true", help="Valida la config y muestra el catálogo")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--log-file", default=None, help="Fichero de log rotativo (p. ej. C:/ProgramData/DataVivo/agent.log)")
    parser.add_argument("--version", action="version", version=f"DataVivo Agent {AGENT_VERSION}")
    args = parser.parse_args(argv)

    _setup_logging(args.log_level, args.log_file)
    log.info("DataVivo Agent %s · config %s", AGENT_VERSION, args.config)
    try:
        config = load_config(args.config)
    except (OSError, ValidationError, ValueError) as exc:
        log.error("Configuración inválida: %s", exc)
        return 2

    if args.check:
        agent = Agent(config)
        for res in agent.catalog():
            cols = ", ".join(f"{c.name}:{c.type}" for c in res.columns) or "(sin columnas / error)"
            print(f"- {res.name}: {cols}")
        return 0

    async def _run() -> None:
        await Agent(config).run_forever()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("Agente detenido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
