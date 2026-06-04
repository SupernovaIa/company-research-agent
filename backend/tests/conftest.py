"""Shared test fixtures.

The loop now runs the output guardrail classifier (block-F) on every successful
dossier. The classifier's Haiku call would hit the network when an API key is
present in the environment. To keep loop unit tests hermetic and free, this
autouse fixture patches ``app.agent.loop.classify_dossier`` to a deterministic
"allow" verdict by default. Tests that exercise the guardrail-block path
override it with their own monkeypatch (the later patch wins).

Classifier unit tests import ``classify_dossier`` from ``app.guardrails.classifier``
directly, so they are unaffected by this patch.

The _null_tracer fixture blanks LANGFUSE_PUBLIC_KEY / SECRET_KEY before each
test and resets the tracer singleton before and after.  Without this, tests
that use _FakeUsage with artificially large token counts (e.g. 10 M tokens to
trigger the budget cap) send real HTTP requests to Langfuse Cloud, producing
traces with $180 phantom cost that pollute the dashboard and skew metrics.
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


@pytest.fixture(autouse=True)
def _null_tracer(monkeypatch):
    """Prevent tests from sending tracing data to Langfuse Cloud.

    Tests use _FakeUsage with unrealistic token counts (e.g. 10 M tokens) to
    exercise budget / cost logic.  The Langfuse tracer is a process-level
    singleton initialised from real credentials in .env.  Without isolation,
    every loop test that touches the real tracer fires HTTP requests to
    Langfuse Cloud with those fake token counts, producing $180 phantom traces
    that inflate the cost dashboard.

    Blanking the key env vars and resetting the singleton before and after each
    test keeps tests hermetic.  reset_tracer() is the supported teardown hook
    documented in tracer.py.
    """
    import app.config as _config_mod
    import app.observability.tracer as _tracer_mod

    # Patch the already-instantiated pydantic-settings singleton directly.
    # monkeypatch.setenv would only update os.environ, which pydantic-settings
    # already read eagerly at Settings() construction time; the frozen attribute
    # value on the existing object would not change.
    monkeypatch.setattr(_config_mod.settings, "langfuse_public_key", "")
    monkeypatch.setattr(_config_mod.settings, "langfuse_secret_key", "")
    _tracer_mod.reset_tracer()
    yield
    _tracer_mod.reset_tracer()
