import pytest

from agentlab import tracing


@pytest.fixture
def store(tmp_path):
    """A fresh trace store for one test; tracing is switched off again afterwards."""
    yield tracing.init(tmp_path / "lab.db")
    tracing.shutdown()
