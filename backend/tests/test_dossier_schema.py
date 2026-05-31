"""Schema tests for the CompanyDossier contract (Spec 01 acceptance criteria)."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.dossier.models import CompanyDossier, dossier_json_schema

SCHEMA_FILE = Path(__file__).resolve().parents[1] / "app" / "dossier" / "dossier.schema.json"


def _usa_dossier() -> dict:
    """Complete dossier for a US listing (AAPL): full market data, a web-cited
    fact, a computed fact, recent news and resolvable sources."""

    return {
        "schema_version": "1.0.0",
        "company": {
            "name": "Apple Inc.",
            "ticker": "AAPL",
            "exchange": "NASDAQ",
            "sector": "Technology",
            "website": "https://www.apple.com",
        },
        "market_data": {
            "price": 195.12,
            "currency": "USD",
            "change_pct": 1.23,
            "market_cap": 3000000000000,
            "pe_ratio": 32.1,
            "forward_pe": 28.4,
            "eps": 6.08,
            "dividend_yield": 0.005,
            "week52_high": 199.62,
            "week52_low": 164.08,
            "as_of": "2026-05-30T20:00:00Z",
            "source": "Yahoo Finance",
        },
        "business_overview": "Apple designs and sells consumer electronics, "
        "software and services worldwide.",
        "key_facts": [
            {
                "text": "Apple reported record services revenue in its latest "
                "quarter.",
                "source_id": "s1",
            },
            {
                "text": "The current price sits about 2.3% below the 52-week high.",
                "basis": "computed from market_data.price and market_data.week52_high",
            },
        ],
        "recent_news": [
            {
                "headline": "Apple unveils new product line",
                "date": "2026-05-28",
                "summary": "Apple announced an updated product line at its event.",
                "source_id": "s2",
            }
        ],
        "sources": [
            {
                "id": "s1",
                "url": "https://investor.apple.com/earnings",
                "title": "Apple Q2 2026 results",
                "accessed_at": "2026-05-31T09:00:00Z",
            },
            {
                "id": "s2",
                "url": "https://news.example.com/apple-event",
                "title": "Apple event coverage",
                "accessed_at": "2026-05-31T09:05:00Z",
            },
        ],
        "generated_at": "2026-05-31T09:10:00Z",
        "run": {"model": "claude-sonnet-4-6", "cost_usd": 0.31, "turns": 9},
    }


def _european_dossier() -> dict:
    """Dossier for a European listing (SAP.DE) with partial market data:
    forward_pe and dividend_yield are null (ADR-004), no computed fact."""

    return {
        "company": {
            "name": "SAP SE",
            "ticker": "SAP.DE",
            "exchange": "XETRA",
            "sector": None,
            "website": None,
        },
        "market_data": {
            "price": 178.40,
            "currency": "EUR",
            "change_pct": -0.45,
            "market_cap": 210000000000,
            "pe_ratio": 24.5,
            "forward_pe": None,
            "eps": 7.28,
            "dividend_yield": None,
            "week52_high": 190.10,
            "week52_low": 130.55,
            "as_of": "2026-05-30T17:30:00+02:00",
            "source": "Yahoo Finance",
        },
        "business_overview": "SAP is a German multinational enterprise software "
        "company.",
        "key_facts": [
            {
                "text": "SAP continues migrating its customer base to the cloud.",
                "source_id": "src-a",
            }
        ],
        "recent_news": [],
        "sources": [
            {
                "id": "src-a",
                "url": "https://www.sap.com/investors",
                "title": "SAP investor relations",
                "accessed_at": "2026-05-31T08:00:00Z",
            }
        ],
        "generated_at": "2026-05-31T08:10:00Z",
        "run": {"model": "claude-sonnet-4-6", "cost_usd": 0.22, "turns": 7},
    }


# --- Acceptance criteria -----------------------------------------------------


def test_validates_us_listing():
    dossier = CompanyDossier.model_validate(_usa_dossier())
    assert dossier.company.ticker == "AAPL"
    assert dossier.market_data.forward_pe == 28.4


def test_validates_european_listing_with_null_fields():
    dossier = CompanyDossier.model_validate(_european_dossier())
    # Optional market fields accept absence of datum.
    assert dossier.market_data.forward_pe is None
    assert dossier.market_data.dividend_yield is None
    # Required structured fields are always present.
    assert dossier.market_data.as_of is not None
    assert dossier.market_data.source == "Yahoo Finance"


def test_orphan_source_id_in_fact_fails():
    payload = _usa_dossier()
    payload["key_facts"][0]["source_id"] = "does-not-exist"
    with pytest.raises(ValidationError, match="orphan source_id"):
        CompanyDossier.model_validate(payload)


def test_orphan_source_id_in_news_fails():
    payload = _usa_dossier()
    payload["recent_news"][0]["source_id"] = "ghost"
    with pytest.raises(ValidationError, match="orphan source_id"):
        CompanyDossier.model_validate(payload)


def test_computed_fact_without_source_id_validates_when_provenance_present():
    payload = _european_dossier()
    payload["key_facts"].append(
        {
            "text": "Price is ~6% below the 52-week high.",
            "basis": "computed from market_data.price and market_data.week52_high",
        }
    )
    dossier = CompanyDossier.model_validate(payload)
    assert dossier.key_facts[-1].source_id is None


def test_computed_fact_referencing_absent_data_fails():
    payload = _european_dossier()
    # forward_pe is null in this dossier: provenance does not resolve.
    payload["key_facts"].append(
        {
            "text": "Forward P/E implies cheaper future earnings.",
            "basis": "computed from market_data.forward_pe",
        }
    )
    with pytest.raises(ValidationError, match="absent data market_data.forward_pe"):
        CompanyDossier.model_validate(payload)


def test_computed_fact_referencing_unknown_field_fails():
    payload = _usa_dossier()
    payload["key_facts"].append(
        {"text": "Bogus metric.", "basis": "computed from market_data.revenue"}
    )
    with pytest.raises(ValidationError, match="unknown market_data field"):
        CompanyDossier.model_validate(payload)


def test_fact_with_both_source_id_and_basis_fails():
    payload = _usa_dossier()
    payload["key_facts"][0]["basis"] = "computed from market_data.price"
    with pytest.raises(ValidationError, match="exactly one"):
        CompanyDossier.model_validate(payload)


def test_fact_with_neither_source_id_nor_basis_fails():
    payload = _usa_dossier()
    del payload["key_facts"][0]["source_id"]
    with pytest.raises(ValidationError, match="exactly one"):
        CompanyDossier.model_validate(payload)


def test_partial_market_data_passes():
    payload = _usa_dossier()
    payload["market_data"]["forward_pe"] = None
    payload["market_data"]["dividend_yield"] = None
    # Remove the computed fact that depends on present data so only the null
    # change is under test.
    payload["key_facts"] = [payload["key_facts"][0]]
    dossier = CompanyDossier.model_validate(payload)
    assert dossier.market_data.forward_pe is None


def test_duplicate_source_id_fails():
    payload = _usa_dossier()
    payload["sources"][1]["id"] = "s1"
    with pytest.raises(ValidationError, match="duplicate id in sources"):
        CompanyDossier.model_validate(payload)


def test_invalid_schema_version_fails():
    payload = _usa_dossier()
    payload["schema_version"] = "v1"
    with pytest.raises(ValidationError, match="semantic"):
        CompanyDossier.model_validate(payload)


def test_operational_metadata_required():
    payload = _usa_dossier()
    del payload["run"]
    with pytest.raises(ValidationError):
        CompanyDossier.model_validate(payload)


# --- Signed-artifact drift guard ---------------------------------------------


def test_committed_schema_matches_model():
    """The committed dossier.schema.json is the signed artifact; it must stay in
    sync with the model. Regenerate it if this fails."""

    committed = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert committed == dossier_json_schema()


def test_json_serialization_is_stable():
    dossier = CompanyDossier.model_validate(_usa_dossier())
    dumped = dossier.model_dump(mode="json")
    # Round-trips cleanly through JSON and re-validates.
    reloaded = CompanyDossier.model_validate(json.loads(json.dumps(dumped)))
    assert reloaded == dossier
