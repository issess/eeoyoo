from __future__ import annotations

import sys

import pytest
from hypothesis import HealthCheck, settings

# Hypothesis default profile: cap examples and disable slow-data health check
settings.register_profile(
    "ci",
    max_examples=200,
    deadline=500,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("ci")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip tests marked @pytest.mark.windows on non-Windows platforms."""
    if sys.platform != "win32":
        skip_marker = pytest.mark.skip(reason="Requires Windows OS (platform gate)")
        for item in items:
            if item.get_closest_marker("windows"):
                item.add_marker(skip_marker)
