"""Tests for the tool inventory declaration (Spec 02 contract)."""

from app.dossier.models import dossier_json_schema
from app.tools.inventory import (
    SUBMIT_DOSSIER_TOOL,
    TOOLS,
)


def test_inventory_declares_all_five_tools():
    names = {t.get("name") for t in TOOLS}
    assert names == {
        "get_market_data",
        "web_search",
        "web_fetch",
        "code_execution",
        "submit_dossier",
    }


def test_server_tools_are_pinned_by_type_and_version():
    by_name = {t["name"]: t for t in TOOLS}
    assert by_name["web_search"]["type"] == "web_search_20260209"
    assert by_name["web_fetch"]["type"] == "web_fetch_20260209"
    assert by_name["code_execution"]["type"] == "code_execution_20260120"


def test_client_tools_have_input_schema():
    by_name = {t["name"]: t for t in TOOLS}
    assert by_name["get_market_data"]["input_schema"]["required"] == ["ticker"]
    assert "input_schema" in by_name["submit_dossier"]


def test_submit_dossier_input_schema_is_the_dossier_contract():
    # ADR-006: the dossier schema is the submit tool input schema.
    assert SUBMIT_DOSSIER_TOOL["input_schema"] == dossier_json_schema()
