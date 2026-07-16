"""Pytest configuration: ensure the repo root is importable and register asyncio."""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class FakeMetricResult:
    """Mimics ragas MetricResult (.value + .to_dict())."""

    def __init__(self, value, reason=None):
        self.value = value
        self._reason = reason

    def to_dict(self):
        return {"value": self.value, "reason": self._reason}


@pytest.fixture
def fake_result():
    return FakeMetricResult
