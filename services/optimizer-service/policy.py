"""Shared policy-mode contract for optimizer and usage APIs."""

from typing import Literal, TypeAlias, cast


PolicyMode: TypeAlias = Literal["conservative", "balanced", "aggressive"]
VALID_POLICY_MODES = frozenset({"conservative", "balanced", "aggressive"})


def canonicalize_policy_mode(value: object) -> str:
    """Normalize formatting while allowing API validation to reject unknown modes."""
    return str(value or "balanced").strip().lower()


def normalize_policy_mode(value: object) -> PolicyMode:
    """Return a safe policy mode for internal callers outside the validated API."""
    mode = canonicalize_policy_mode(value)
    if mode not in VALID_POLICY_MODES:
        mode = "balanced"
    return cast(PolicyMode, mode)
