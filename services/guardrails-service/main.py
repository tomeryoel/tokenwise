"""guardrails-service (Day 3: real MVP guardrails).

Implements safety governance (secrets, PII, prompt injection) and cost
governance (no-content blocking and low-context routing signals) with
deterministic, easy-to-explain rules. No ML yet - rules + regex only.

The /check/input response contract is preserved (same field names) so the n8n
workflow and the React Decision Receipt keep working; new fields are additive.
"""
import re

from fastapi import FastAPI
from pydantic import BaseModel

SERVICE_NAME = "guardrails-service"

# Simple, deterministic cost model. $0.03 / 1k tokens premium baseline.
PREMIUM_PRICE_PER_TOKEN = 0.00003

app = FastAPI(title=SERVICE_NAME)


# --------------------------------------------------------------------------- #
# Detection rules
# --------------------------------------------------------------------------- #
INJECTION_PATTERNS = [
    re.compile(
        r"^\s*(?:please\s+)?(?:ignore|disregard)(?:\s+all)?\s+previous instructions\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:please\s+)?(?:reveal|show)(?:\s+me)?\s+"
        r"(?:your\s+system prompt|the\s+system prompt|hidden instructions)\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*(?:please\s+)?bypass(?:\s+the)?\s+policy\b", re.IGNORECASE),
    re.compile(
        r"^\s*(?:please\s+)?act as if there (?:are|were) no rules\b",
        re.IGNORECASE,
    ),
]

SECRET_REGEXES = [
    re.compile(r"sk-[A-Za-z0-9]{8,}"),                       # OpenAI-style keys
    re.compile(r"(?i)api[_-]?key\s*[=:]\s*\S+"),             # api_key=...
    re.compile(r"(?i)\b(?:OPENAI_API_KEY|GITHUB_TOKEN)\b\s*[=:]\s*\S+"),
    re.compile(r"gh[pous]_[A-Za-z0-9]{20,}"),                # GitHub tokens
]
# Long high-entropy-ish tokens (must mix letters + digits to reduce false hits).
HIGH_ENTROPY_RE = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
ID_RE = re.compile(r"\b\d{9}\b")            # Israeli-ID-like 9 digit number
PHONE_RE = re.compile(r"\+?\d[\d\-\s]{6,}\d")

WORDLIKE_RE = re.compile(r"\w+", re.UNICODE)


def estimate_tokens(text: str) -> int:
    words = len(text.split())
    return round(words * 1.3)


def cost_saved(tokens: int) -> float:
    return round(tokens * PREMIUM_PRICE_PER_TOKEN, 6)


def _is_high_entropy(tok: str) -> bool:
    return bool(re.search(r"[A-Za-z]", tok)) and bool(re.search(r"\d", tok))


def redact_secrets(text: str):
    """Return (redacted_text, found_bool)."""
    redacted = text
    found = False
    for rx in SECRET_REGEXES:
        if rx.search(redacted):
            found = True
            redacted = rx.sub("[REDACTED_SECRET]", redacted)

    def _ent_sub(m: re.Match) -> str:
        return "[REDACTED_SECRET]" if _is_high_entropy(m.group(0)) else m.group(0)

    new = HIGH_ENTROPY_RE.sub(_ent_sub, redacted)
    if new != redacted:
        found = True
    return new, found


def redact_pii(text: str):
    """Return (redacted_text, found_bool). Order: email, 9-digit id, phone."""
    found = {"v": False}

    def mark(replacement: str):
        def _sub(_m: re.Match) -> str:
            found["v"] = True
            return replacement
        return _sub

    redacted = EMAIL_RE.sub(mark("[REDACTED_EMAIL]"), text)
    redacted = ID_RE.sub(mark("[REDACTED_ID]"), redacted)
    redacted = PHONE_RE.sub(mark("[REDACTED_PHONE]"), redacted)
    return redacted, found["v"]


def meaningful_units(text: str) -> list[str]:
    return WORDLIKE_RE.findall(text)


def is_non_meaningful(text: str) -> bool:
    """Conservatively reject obvious noise without judging the prompt's topic."""
    units = meaningful_units(text)
    if not units:
        return True

    letters = [char.casefold() for char in text if char.isalpha()]
    if len(letters) >= 4 and len(set(letters)) == 1:
        return True

    return False


def make_response(prompt: str, **override) -> dict:
    tokens = estimate_tokens(prompt)
    resp = {
        "pass": True,
        "reason": "passed",
        "policy_triggered": None,
        "severity": "low",
        "detected_risk_type": None,
        "contains_sensitive_data": False,
        "requires_redaction": False,
        "recommended_route": "external",
        "allow_external_model": True,
        "require_local_model": False,
        "require_human_approval": False,
        "estimated_cost_risk": "low",
        "estimated_tokens": tokens,
        "cost_saved_by_blocking": 0.0,
        "cost_control_action": "standard",
        "cost_control_reason": None,
        "prefer_low_cost_tier": False,
        "safe_text": prompt,
        "redacted_text": None,
    }
    resp.update(override)
    return resp


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class InputCheckRequest(BaseModel):
    request_id: str | None = None
    prompt: str = ""
    policy_mode: str = "balanced"


class OutputCheckRequest(BaseModel):
    request_id: str | None = None
    answer: str = ""


UNSUPPORTED_ROI_CLAIMS = [
    "guaranteed savings",
    "guarantee savings",
    "guaranteed to save",
    "100% cost reduction",
    "always saves money",
    "always save money",
]


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/check/input")
def check_input(req: InputCheckRequest):
    prompt = req.prompt or ""
    stripped = prompt.strip()
    tokens = estimate_tokens(prompt)

    # 1) Empty / whitespace-only -> cost governance block.
    if stripped == "":
        return make_response(prompt, **{
            "pass": False,
            "reason": "empty_prompt",
            "detected_risk_type": "low_value_prompt",
            "policy_triggered": "cost_governance",
            "estimated_cost_risk": "low",
            "cost_saved_by_blocking": cost_saved(tokens),
            "cost_control_action": "block_no_content",
            "cost_control_reason": "empty input would waste a model call",
            "safe_text": None,
        })

    # 2) Prompt injection -> safety governance block (high severity).
    if any(pattern.search(stripped) for pattern in INJECTION_PATTERNS):
        return make_response(prompt, **{
            "pass": False,
            "reason": "prompt_injection_detected",
            "detected_risk_type": "prompt_injection",
            "policy_triggered": "safety_governance",
            "severity": "high",
            "requires_redaction": False,
            "allow_external_model": False,
            "require_local_model": False,
            "require_human_approval": False,
            "estimated_cost_risk": "low",
            "cost_saved_by_blocking": cost_saved(tokens),
            "cost_control_action": "block_safety",
            "cost_control_reason": "unsafe request stopped before model execution",
        })

    # 3) Secrets -> block, high severity, local-only, redacted.
    redacted_secret, has_secret = redact_secrets(prompt)
    if has_secret:
        return make_response(prompt, **{
            "pass": False,
            "reason": "secret_detected",
            "detected_risk_type": "secret",
            "policy_triggered": "safety_governance",
            "severity": "high",
            "contains_sensitive_data": True,
            "requires_redaction": True,
            "recommended_route": "local",
            "allow_external_model": False,
            "require_local_model": True,
            "estimated_cost_risk": "low",
            "cost_saved_by_blocking": cost_saved(tokens),
            "cost_control_action": "block_safety",
            "cost_control_reason": "secret stopped before model execution",
            "safe_text": redacted_secret,
            "redacted_text": redacted_secret,
        })

    # 4) PII -> allow after redaction (pass with redaction).
    redacted_pii, has_pii = redact_pii(prompt)
    if has_pii:
        return make_response(prompt, **{
            "pass": True,
            "reason": "pii_detected_redacted",
            "detected_risk_type": "pii",
            "policy_triggered": "safety_governance",
            "severity": "medium",
            "contains_sensitive_data": True,
            "requires_redaction": True,
            "recommended_route": "local",
            "allow_external_model": False,
            "require_local_model": True,
            "estimated_cost_risk": "low",
            "cost_saved_by_blocking": 0.0,
            "cost_control_action": "local_only",
            "cost_control_reason": "sensitive data stays on the local model",
            "safe_text": redacted_pii,
            "redacted_text": redacted_pii,
        })

    # 5) Obvious noise -> cost governance block. Topic is never a block reason.
    if is_non_meaningful(stripped):
        return make_response(prompt, **{
            "pass": False,
            "reason": "non_meaningful_prompt",
            "detected_risk_type": "low_value_prompt",
            "policy_triggered": "cost_governance",
            "estimated_cost_risk": "low",
            "cost_saved_by_blocking": cost_saved(tokens),
            "cost_control_action": "block_no_content",
            "cost_control_reason": "obvious noise would waste a model call",
        })

    # 6) Short/low-context prompts remain legitimate, but carry a real routing
    # signal so LangGraph can prefer a cheaper tier when quality permits.
    if len(meaningful_units(stripped)) < 3:
        return make_response(prompt, **{
            "pass": True,
            "reason": "low_context_cost_optimization",
            "policy_triggered": "cost_governance",
            "recommended_route": "cheap",
            "cost_control_action": "prefer_low_cost_tier",
            "cost_control_reason": "low-context request should start on a low-cost tier",
            "prefer_low_cost_tier": True,
        })

    # Passed all checks.
    return make_response(prompt, **{"reason": "passed"})


@app.post("/check/output")
def check_output(req: OutputCheckRequest):
    text = req.answer or ""
    issues: list[str] = []

    redacted, has_secret = redact_secrets(text)
    if has_secret:
        issues.append("leaked_secret_redacted")

    low = text.lower()
    for claim in UNSUPPORTED_ROI_CLAIMS:
        if claim in low:
            issues.append(f"unsupported_roi_claim:{claim}")

    passed = not any(i.startswith("unsupported_roi_claim") for i in issues)
    return {
        "pass": passed,
        "issues": issues,
        "redacted_text": redacted if has_secret else None,
    }
