from __future__ import annotations

from cursor.router import CursorRouteRequest, recommend_cursor_route


def test_recommend_high_complexity_prefers_premium():
    result = recommend_cursor_route(
        CursorRouteRequest(
            objective="Design a multi-region failover architecture for our payment service.",
            task_type="architecture_design",
            complexity_level="high",
            policy_mode="balanced",
            workflow="plan",
        )
    )
    assert result.recommended_model_id in {
        "claude-opus-5-thinking-high",
        "claude-fable-5-thinking-high",
        "cursor-grok-4.5-high-fast",
    }


def test_recommend_aggressive_low_complexity_prefers_economy():
    result = recommend_cursor_route(
        CursorRouteRequest(
            objective="Rename this helper function and update imports.",
            task_type="refactor",
            complexity_level="low",
            policy_mode="aggressive",
            workflow="agent",
        )
    )
    assert result.recommended_model_id in {
        "composer-2.5-fast",
        "gpt-5.6-sol-medium",
    }


def test_prefer_auto_returns_auto_with_resolution_reason():
    result = recommend_cursor_route(
        CursorRouteRequest(
            objective="Fix a flaky unit test in auth middleware.",
            task_type="bug_fix",
            complexity_level="medium",
            policy_mode="balanced",
            workflow="agent",
            prefer_auto=True,
        )
    )
    assert result.recommended_model_id == "auto"
    assert result.resolved_from_auto is True
    assert any("Auto resolves" in reason for reason in result.reasons)
