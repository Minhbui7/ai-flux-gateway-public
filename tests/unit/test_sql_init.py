import importlib.util
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "sql" / "init-managed-identity.py"
SPEC = importlib.util.spec_from_file_location("sql_init", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_principal_sid_uses_client_id_binary_order() -> None:
    client_id = "81dc75eb-a908-4be6-ad44-88a045ebc17b"
    sql = module.principal_sql("aiflux-fdpo-dev-api-identity", client_id)
    assert "0x" + UUID(client_id).bytes_le.hex() in sql
    assert "TYPE=E" in sql
    assert "FROM EXTERNAL PROVIDER" not in sql
    assert "identity mismatch" in sql


def test_repair_is_limited_to_known_legacy_identity() -> None:
    sql = module.principal_sql(
        "aiflux-fdpo-dev-api-identity",
        "81dc75eb-a908-4be6-ad44-88a045ebc17b",
        "d655283f-9bba-4bf8-9825-6e3d05a5bf13",
    )
    assert "sid=0x3f2855d6ba9bf84b98256e3d05a5bf13 AND type='E') DROP USER" in sql


@pytest.mark.parametrize("name", ["evil]; DROP USER dbo;--", "bad'user", "", "x" * 129])
def test_principal_identifiers_are_restricted(name: str) -> None:
    with pytest.raises(ValueError):
        module.principal_sql(name, "d655283f-9bba-4bf8-9825-6e3d05a5bf13")


def test_marker_contains_only_supplied_sanitized_status() -> None:
    target = Path("status.json")
    with patch.object(Path, "write_text") as write, patch.object(Path, "replace") as replace:
        module.write_marker(target, {"status": "probe_ok"})
    write.assert_called_once_with('{"status": "probe_ok"}', encoding="utf-8")
    replace.assert_called_once_with(target)
