from connectors.cursor.models import normalize_cursor_model_id


def test_normalize_cursor_display_names():
    assert normalize_cursor_model_id("Composer 2.5") == "composer-2.5-fast"
    assert normalize_cursor_model_id("GPT-5.6 Sol") == "gpt-5.6-sol-medium"
    assert normalize_cursor_model_id("Opus 5") == "claude-opus-5-thinking-high"
    assert normalize_cursor_model_id("auto") == "auto"
