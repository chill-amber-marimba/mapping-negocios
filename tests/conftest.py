"""Shared pytest fixtures."""

import pytest

from fakes import FakeGateway


@pytest.fixture
def gateway() -> FakeGateway:
    """A fresh fake gateway."""
    return FakeGateway()
