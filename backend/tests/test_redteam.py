"""Tests for the red-team harness (Spec 09)."""

from __future__ import annotations

import re
from pathlib import Path

from app.redteam.payloads import PAYLOADS
from app.redteam.runner import THRESHOLD, run_checklist

_CHECKLIST = (
    Path(__file__).resolve().parents[2] / "security" / "red-team-checklist.md"
)


def test_at_least_20_payloads_across_four_layers():
    assert len(PAYLOADS) >= 20
    layers = {p.expected_layer for p in PAYLOADS}
    assert layers == {"L1", "L2", "L3", "L4"}


def test_payload_ids_are_unique():
    ids = [p.id for p in PAYLOADS]
    assert len(ids) == len(set(ids))


def test_checklist_runs_and_meets_threshold():
    report = run_checklist()
    assert report.total == len(PAYLOADS)
    assert report.gate_ok
    assert report.pass_rate >= THRESHOLD


def test_every_payload_blocked_by_its_expected_layer():
    report = run_checklist()
    for r in report.results:
        assert r.passed, (r.payload.id, r.actual_layer, r.detail)
        assert r.actual_layer == r.payload.expected_layer


def test_each_layer_blocks_at_least_one_payload():
    report = run_checklist()
    covered = report.layers_covered()
    for layer in ("L1", "L2", "L3", "L4"):
        assert covered.get(layer, 0) >= 1


def test_checklist_md_in_sync_with_payloads():
    """The human checklist must list exactly the canonical payload IDs."""
    text = _CHECKLIST.read_text(encoding="utf-8")
    md_ids = set(re.findall(r"INJ-\d{3}", text))
    code_ids = {p.id for p in PAYLOADS}
    assert md_ids == code_ids, md_ids.symmetric_difference(code_ids)
