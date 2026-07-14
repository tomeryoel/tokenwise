"""Pytest configuration for optimizer-service."""

import pytest

from providers.registry import clear_test_transports


@pytest.fixture(autouse=True)
def _clear_provider_test_transports():
    clear_test_transports()
    yield
    clear_test_transports()
