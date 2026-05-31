"""Shared test fixtures.

The loop now runs the output guardrail classifier (block-F) on every successful
dossier. The classifier's Haiku call would hit the network when an API key is
present in the environment. To keep loop unit tests hermetic and free, this
autouse fixture patches ``app.agent.loop.classify_dossier`` to a deterministic
"allow" verdict by default. Tests that exercise the guardrail-block path
override it with their own monkeypatch (the later patch wins).

Classifier unit tests import ``classify_dossier`` from ``app.guardrails.classifier``
directly, so they are unaffected by this patch.
"""

from __future__ import annotations

import pytest

from app.guardrails.classifier import Verdict


@pytest.fixture(autouse=True)
def _allow_output_guardrail(monkeypatch):
    monkeypatch.setattr(
        "app.agent.loop.classify_dossier",
        lambda dossier, **kw: Verdict(True, "test-allow", "classifier"),
    )
