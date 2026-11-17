import datetime as dt
from decimal import Decimal

import pytest

from config import AgentConfig
from serialization import to_jsonable
from sql_guard import ReadOnlyViolation, assert_not_write_statement, assert_read_only_query


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM t",
        "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
        "SELECT REPLACE(nombre, 'a', 'b') FROM t",
        "SELECT 'DROP TABLE x' AS texto FROM t",  # palabra clave dentro de un literal
        "SELECT a FROM t;",
    ],
)
def test_read_only_query_accepts(sql):
    assert_read_only_query(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM t",
        "SELECT 1; DROP TABLE t",
        "SELECT * INTO copia FROM t",
        "UPDATE t SET a = 1",
        "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x",
        "EXEC xp_cmdshell 'dir'",
        "/* comentario */ INSERT INTO t VALUES (1)",
        "",
    ],
)
def test_read_only_query_rejects(sql):
    with pytest.raises(ReadOnlyViolation):
        assert_read_only_query(sql)


def test_statement_guard():
    assert_not_write_statement("SELECT 1")
    assert_not_write_statement("PRAGMA table_info(x)")
    with pytest.raises(ReadOnlyViolation):
        assert_not_write_statement("  drop table x")


def test_config_rejects_write_query_and_writes(config):
    raw = config.model_dump(by_alias=True)
    raw["sources"]["erp"]["tables"]["mala"] = {"query": "DELETE FROM CLIENTES", "columns": ["A"]}
    with pytest.raises(ValueError):
        AgentConfig.model_validate(raw)

    raw = config.model_dump(by_alias=True)
    raw["security"]["allow_writes"] = True
    with pytest.raises(ValueError):
        AgentConfig.model_validate(raw)


def test_config_requires_tls(config):
    raw = config.model_dump(by_alias=True)
    raw["cloud"]["allow_insecure"] = False
    with pytest.raises(ValueError):
        AgentConfig.model_validate(raw)


def test_serialization():
    assert to_jsonable(Decimal("10.50")) == "10.50"
    assert to_jsonable(Decimal("10.50"), "float") == 10.5
    assert to_jsonable(dt.datetime(2024, 1, 2, 3, 4, 5)) == "2024-01-02T03:04:05"
    assert to_jsonable(dt.date(2024, 1, 2)) == "2024-01-02"
    assert to_jsonable(float("nan")) is None
    assert to_jsonable(b"\x00\x01") == "AAE="
