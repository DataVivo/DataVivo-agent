import asyncio
import json

import pytest

from agent import Agent
from connectors import InvalidRequestError, build_resources
from protocol import Filter


@pytest.fixture
def resources(config):
    return build_resources(config)


def q(resources, name, **kw):
    connector, table = resources[name]
    return connector.query_data(table, **kw)


# ---- SQL --------------------------------------------------------------------------
def test_sql_whitelist_hides_columns(resources):
    rows = q(resources, "clientes")
    assert len(rows) == 3
    assert "PASSWORD" not in rows[0]
    assert rows[0]["FECHA_ALTA"] == "2020-01-15"


def test_sql_filters_are_bound(resources):
    rows = q(resources, "clientes", filters=[Filter(field="ciudad", op="eq", value="Madrid")])
    assert [r["CODIGO"] for r in rows] == [1, 3]
    rows = q(resources, "clientes", filters=[Filter(field="SALDO", op="gt", value="100")])
    assert {r["CODIGO"] for r in rows} == {1, 3}
    # Intento de inyección: se trata como un valor literal
    rows = q(resources, "clientes", filters=[Filter(field="CIUDAD", value="Madrid' OR '1'='1")])
    assert rows == []


def test_sql_rejects_non_whitelisted(resources):
    with pytest.raises(InvalidRequestError):
        q(resources, "clientes", filters=[Filter(field="PASSWORD", value="x")])
    with pytest.raises(InvalidRequestError):
        q(resources, "clientes", fields=["PASSWORD"])
    with pytest.raises(InvalidRequestError):
        q(resources, "clientes", filters=[Filter(field="NOMBRE); DROP TABLE CLIENTES;--", value="x")])


def test_sql_like_in_paging_and_limit(resources):
    rows = q(resources, "clientes", filters=[Filter(field="NOMBRE", op="like", value="%lópez%")])
    assert [r["CODIGO"] for r in rows] == [1]
    rows = q(resources, "clientes", filters=[Filter(field="CODIGO", op="in", value=["2", "3"])])
    assert [r["CODIGO"] for r in rows] == [2, 3]
    rows = q(resources, "clientes", limit=1, offset=1)
    assert [r["CODIGO"] for r in rows] == [2]
    assert len(q(resources, "clientes", limit=10_000)) == 3  # recortado a max_limit


def test_sql_custom_query(resources):
    rows = q(resources, "madrid", filters=[Filter(field="CODIGO", op="gte", value=2)])
    assert rows == [{"CODIGO": 3, "NOMBRE": "Talleres Martín"}]


def test_sql_session_is_read_only(resources):
    connector, _ = resources["clientes"]
    from sqlalchemy import text

    from sql_guard import ReadOnlyViolation

    with pytest.raises(ReadOnlyViolation):
        with connector.engine.connect() as conn:
            conn.execute(text("DELETE FROM CLIENTES"))


# ---- DBF --------------------------------------------------------------------------
def test_dbf(resources):
    schema = resources["articulos"][0].get_schema()["articulos"]
    assert [c.name for c in schema] == ["CODIGO", "DESCRIP", "PVP", "STOCK", "ALTA", "ACTIVO"]

    rows = q(resources, "articulos")
    assert len(rows) == 3  # el registro borrado no aparece
    assert rows[1]["DESCRIP"] == "Martillo carpintería"
    assert rows[0]["ALTA"] == "2020-01-01"

    rows = q(resources, "articulos", filters=[Filter(field="stock", op="gt", value="0"),
                                              Filter(field="ACTIVO", value="true")])
    assert [r["CODIGO"] for r in rows] == ["A001", "A002"]
    rows = q(resources, "articulos", filters=[Filter(field="ALTA", op="gte", value="2021-01-01")], fields=["codigo"])
    assert rows == [{"CODIGO": "A002"}, {"CODIGO": "A003"}]


# ---- Excel / CSV ------------------------------------------------------------------
def test_excel(resources):
    rows = q(resources, "stock")
    assert rows[2]["Descripción"] is None
    assert rows[0]["Fecha"] == "2024-01-01T00:00:00"
    rows = q(resources, "stock", filters=[Filter(field="unidades", op="gte", value="7")])
    assert [r["Referencia"] for r in rows] == ["R1", "R3"]


def test_csv(resources):
    rows = q(resources, "tarifas", filters=[Filter(field="codigo", value="T2")])
    assert rows == [{"codigo": "T2", "precio": "20"}]


# ---- Agente ------------------------------------------------------------------------
def test_agent_handle(config):
    agent = Agent(config)
    assert {r.name for r in agent.catalog()} == {"clientes", "madrid", "articulos", "stock", "tarifas"}

    async def run(msg):
        return await agent.handle(json.dumps(msg))

    ok = asyncio.run(run({"type": "query", "id": "1", "resource": "clientes", "limit": 2}))
    assert ok.ok and len(ok.rows) == 2

    bad = asyncio.run(run({"type": "query", "id": "2", "resource": "clientes",
                           "filters": [{"field": "PASSWORD", "op": "eq", "value": "x"}]}))
    assert not bad.ok and bad.error_code == "invalid_request"

    unknown = asyncio.run(run({"type": "query", "id": "3", "resource": "CLIENTES_REAL"}))
    assert unknown.error_code == "unknown_resource"

    assert asyncio.run(run({"type": "exec", "sql": "DROP TABLE x"})) is None
