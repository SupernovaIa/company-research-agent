"""Indirect prompt injection defenses (input side).

Layered defense against malicious instructions embedded in untrusted tool
content (web_search, web_fetch, get_market_data). See spec 04, spec 09 and
ADR-013.

This module is intentionally dependency-free (stdlib only) so the defenses and
the red-team runner can execute without the model SDK, an API key or any network
access. The pieces here are:

- ``wrap_external_content``: layer L1, wraps tool output in explicit delimiters
  and neutralizes any attempt to forge the boundary tokens.
- ``heuristic_scan``: the deterministic half of layer L3 (output classifier),
  a cheap regex pre-filter that runs before the Haiku semantic backstop.
- ``READONLY_TOOL_INVENTORY`` / ``capability_is_available``: layer L4, minimum
  privilege — the declared read-only tool surface, used to confirm a demanded
  side-effecting action maps to no available tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- Layer L1: external content delimiters ----------------------------------

EXTERNAL_CONTENT_OPEN = "<<UNTRUSTED_TOOL_CONTENT source={source}>>"
EXTERNAL_CONTENT_CLOSE = "<<END_UNTRUSTED_TOOL_CONTENT>>"

# Tokens the content must never be able to forge to break out of its data frame.
# Matched loosely (any casing, optional source attribute, slack whitespace) so a
# payload cannot smuggle a fake boundary by tweaking case or spacing.
_BOUNDARY_FORGERY = re.compile(
    r"<<\s*/?\s*(END_)?UNTRUSTED_TOOL_CONTENT[^>]*>>",
    re.IGNORECASE,
)
# Attempts to impersonate a conversation turn or a system block inside data.
_TURN_FORGERY = re.compile(
    r"(?im)^\s*(system|assistant|user|human)\s*:\s*",
)


def sanitize_external_content(content: str) -> str:
    """Defang boundary/turn forgery in untrusted content before wrapping."""
    content = _BOUNDARY_FORGERY.sub("[redacted-delimiter]", content)
    content = _TURN_FORGERY.sub("[redacted-role] ", content)
    return content


def wrap_external_content(source: str, content: str) -> str:
    """Wrap untrusted tool output in explicit, forgery-proof delimiters.

    The model is told (system prompt) that anything between these delimiters is
    data, never instructions. We sanitize first so the content cannot counterfeit
    the closing delimiter and escape the data frame.
    """
    safe = sanitize_external_content(str(content))
    return f"{EXTERNAL_CONTENT_OPEN.format(source=source)}\n{safe}\n{EXTERNAL_CONTENT_CLOSE}"


def has_forgery(content: str) -> bool:
    """True if content contains a boundary or conversation-turn forgery."""
    return bool(_BOUNDARY_FORGERY.search(content) or _TURN_FORGERY.search(content))


def is_frame_intact(wrapped: str) -> bool:
    """True if a wrapped blob has exactly one opening and one closing boundary.

    Used by the red-team runner to assert a delimiter-targeted payload did not
    manage to forge an extra boundary inside the data frame.
    """
    return len(_BOUNDARY_FORGERY.findall(wrapped)) == 2


# --- Layer L3: deterministic output pre-filter ------------------------------

# Each pattern maps to an attack category. Matching any of these in the
# serialized dossier blocks it deterministically, before the Haiku classifier.
_SCAN_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    (
        "prompt_leak",
        re.compile(
            r"(you are a financial research agent"
            r"|system prompt"
            r"|tool (definition|schema|description)s?"
            r"|classifier (system )?prompt"
            r"|untrusted_tool_content)",
            re.IGNORECASE,
        ),
    ),
    (
        "injected_instruction",
        re.compile(
            r"(ignore (all |the )?(previous|prior|above) instructions"
            r"|disregard (your|the|all) .{0,20}instructions"
            r"|new instructions\s*:"
            r"|from now on,? you"
            r"|you must now"
            r"|override .{0,20}(rules|instructions))",
            re.IGNORECASE,
        ),
    ),
    (
        "out_of_scope_action",
        re.compile(
            r"(send (an? )?email"
            r"|exfiltrat\w*"
            r"|\btransfer\b.{0,20}\bfunds?\b"
            r"|\bwire\b.{0,20}(money|funds)"
            r"|\bdelete\b.{0,20}(file|record|data)"
            r"|rm\s+-rf"
            r"|curl\s+http"
            r"|api[_\s-]?key"
            r"|password)",
            re.IGNORECASE,
        ),
    ),
    (
        "fabrication_marker",
        re.compile(
            r"(lorem ipsum|as an ai|\[?placeholder\]?|\bTODO\b|\bFIXME\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "out_of_schema_verdict",
        re.compile(
            r"(\bstrong buy\b|\bstrong sell\b"
            r"|\b(buy|sell|hold) (recommendation|rating)\b"
            r"|\brecommendation\s*:\s*(buy|sell|hold)"
            r"|\brating\s*:\s*(buy|sell|hold)"
            r"|\bprice target\b)",
            re.IGNORECASE,
        ),
    ),
)


@dataclass
class ScanResult:
    blocked: bool
    category: str | None = None
    match: str | None = None


def heuristic_scan(text: str) -> ScanResult:
    """Deterministic injection/leakage scan over agent output.

    Returns the first matching category, or a clean result. Cheap, no API call;
    pairs with the Haiku classifier for semantic coverage (defense in depth, see
    spec 04 / spec 09 layer 3).
    """
    for category, pattern in _SCAN_PATTERNS:
        m = pattern.search(text)
        if m:
            return ScanResult(blocked=True, category=category, match=m.group(0))
    return ScanResult(blocked=False)


# --- Layer L4: minimum privilege --------------------------------------------

# The complete read-only tool surface exposed to the model. Mirrors the names in
# tools/inventory.py TOOLS; kept here as a dependency-free constant so the
# minimum-privilege guarantee can be asserted without importing the SDK-bound
# inventory. None of these tools write, delete, send or have external side
# effects (ADR-006, ADR-009 minimum privilege).
READONLY_TOOL_INVENTORY: tuple[str, ...] = (
    "get_market_data",
    "submit_dossier",
    "web_search",
    "web_fetch",
    "code_execution",
)

# Capabilities that, by design, no tool provides. A payload demanding any of
# these is defended by minimum privilege: there is simply no tool to abuse.
FORBIDDEN_CAPABILITIES: tuple[str, ...] = (
    "send_email",
    "delete",
    "write_file",
    "execute_shell",
    "transfer_funds",
    "http_post",
    "modify_record",
)


def capability_is_available(capability: str) -> bool:
    """Whether a requested capability maps to any available tool.

    Minimum privilege means side-effecting capabilities return False: the worst
    outcome of a hijack is a wrong dossier, never a destructive action.
    """
    return capability in READONLY_TOOL_INVENTORY
