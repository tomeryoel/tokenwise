from connectors.cursor.router import compare_models, recommend_route


def test_offline_recommend_high_complexity():
    result = recommend_route(
        objective="Design a multi-region failover architecture for payments.",
        workflow="plan",
        policy_mode="balanced",
    )
    assert result.recommended_model_id in {
        "claude-opus-5-thinking-high",
        "claude-fable-5-thinking-high",
        "cursor-grok-4.5-high-fast",
    }


def test_offline_recommend_aggressive_low():
    result = recommend_route(
        objective="Rename this helper function.",
        workflow="agent",
        policy_mode="aggressive",
    )
    assert result.recommended_model_id in {
        "composer-2.5-fast",
        "gpt-5.6-sol-medium",
    }


def test_compare_overpowered():
    comparison = compare_models(
        "claude-opus-5-thinking-high",
        "composer-2.5-fast",
    )
    assert comparison["fit"] == "overpowered"
