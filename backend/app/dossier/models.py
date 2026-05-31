"""Pydantic v2 contract for the agent output: the ``CompanyDossier``.

This module is the signed output contract of the agent (Spec 01). It defines the
dossier and its sub-schemas, and enforces the citation rules across the document:

- ``MarketData`` comes from a structured provider (yfinance, ADR-004): it carries
  ``source`` + ``as_of`` and no ``source_id``.
- A ``Fact`` retrieved from the web cites a ``source_id`` that must resolve to a
  ``Source`` in ``sources``.
- A ``Fact`` derived from a deterministic computation (code execution, ADR-011)
  carries a ``basis`` instead of a ``source_id``; its provenance must resolve to
  data present in the dossier (the ``market_data`` fields it was computed from),
  so the value is reproducible and not invented.
- A ``NewsItem`` always cites a ``source_id``.

The JSON schema derived from ``CompanyDossier`` is the artifact wired into the
``submit_dossier`` tool (ADR-006) and consumed by the evaluation set.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

# Semantic version of the dossier contract. Bumped on schema changes; consumers
# and the evaluation set key on it (Spec 01, deprecation policy).
SCHEMA_VERSION = "1.0.0"

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
# A computed Fact references the market_data fields it was derived from, e.g.
# "computed from market_data.week52_high and market_data.price".
_MARKET_DATA_REF_RE = re.compile(r"market_data\.(\w+)")


class Company(BaseModel):
    """Identity of the researched company."""

    name: str
    ticker: str
    exchange: str
    sector: str | None = None
    website: HttpUrl | None = None


class MarketData(BaseModel):
    """Structured market data from the provider (yfinance, ADR-004).

    Carries ``source`` + ``as_of`` and never a ``source_id``: it is a structured
    source of truth, not cited web prose. Fields with no datum are ``null`` and
    are never invented; European listings tend to carry more ``null`` (ADR-004).
    """

    price: float
    currency: str
    change_pct: float | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    forward_pe: float | None = None
    eps: float | None = None
    dividend_yield: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    as_of: datetime
    source: str


class Fact(BaseModel):
    """A qualitative key fact.

    Carries exactly one of:

    - ``source_id``: the fact was retrieved from the web and cites a ``Source``.
    - ``basis``: the fact was derived from a deterministic computation. The
      ``basis`` describes the derivation and references the dossier data it was
      computed from (e.g. ``"computed from market_data.week52_high"``).
    """

    text: str
    source_id: str | None = None
    basis: str | None = None

    @model_validator(mode="after")
    def _exactly_one_provenance(self) -> Fact:
        has_source = self.source_id is not None
        has_basis = self.basis is not None
        if has_source == has_basis:
            raise ValueError(
                "a Fact must carry exactly one of 'source_id' (retrieved from the "
                "web) or 'basis' (derived from a computation)"
            )
        return self


class NewsItem(BaseModel):
    """A recent news item. Always cites a ``source_id``."""

    headline: str
    date: date
    summary: str
    source_id: str


class Source(BaseModel):
    """A cited source. Every ``source_id`` referenced in the dossier resolves
    to one of these."""

    id: str
    url: HttpUrl
    title: str
    accessed_at: datetime


class RunMeta(BaseModel):
    """Operational metadata of the execution that produced this dossier."""

    model: str
    cost_usd: float = Field(ge=0)
    turns: int = Field(ge=0)


class CompanyDossier(BaseModel):
    """The agent output contract.

    A point-in-time, citable snapshot (ADR-012, stateless by design). Cross-field
    validation enforces that every cited ``source_id`` resolves to a listed
    ``Source`` and that every computed ``Fact`` resolves its provenance to data
    present in the dossier.
    """

    schema_version: str = SCHEMA_VERSION
    company: Company
    market_data: MarketData
    business_overview: str
    key_facts: list[Fact] = Field(default_factory=list)
    recent_news: list[NewsItem] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    generated_at: datetime
    run: RunMeta

    @field_validator("schema_version")
    @classmethod
    def _validate_semver(cls, value: str) -> str:
        if not _SEMVER_RE.match(value):
            raise ValueError(f"schema_version must be semantic (X.Y.Z), got {value!r}")
        return value

    @model_validator(mode="after")
    def _validate_citations(self) -> CompanyDossier:
        source_ids = [s.id for s in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("duplicate id in sources: each Source id must be unique")
        known = set(source_ids)

        for fact in self.key_facts:
            if fact.source_id is not None and fact.source_id not in known:
                raise ValueError(
                    f"orphan source_id {fact.source_id!r} in key_facts: "
                    "not present in sources"
                )

        for item in self.recent_news:
            if item.source_id not in known:
                raise ValueError(
                    f"orphan source_id {item.source_id!r} in recent_news: "
                    "not present in sources"
                )

        # Provenance of computed facts must resolve to present (non-null) data.
        market_data_fields = set(MarketData.model_fields)
        for fact in self.key_facts:
            if fact.basis is None:
                continue
            referenced = _MARKET_DATA_REF_RE.findall(fact.basis)
            for field_name in referenced:
                if field_name not in market_data_fields:
                    raise ValueError(
                        f"computed Fact references unknown market_data field "
                        f"{field_name!r}"
                    )
                if getattr(self.market_data, field_name) is None:
                    raise ValueError(
                        f"computed Fact references absent data "
                        f"market_data.{field_name}: provenance does not resolve"
                    )

        return self


def dossier_json_schema() -> dict:
    """Return the JSON schema of the dossier contract.

    This is the signed artifact wired into ``submit_dossier`` (ADR-006) and used
    by the evaluation set. The committed ``dossier.schema.json`` is generated from
    this function; a test guards against drift.
    """

    return CompanyDossier.model_json_schema()
