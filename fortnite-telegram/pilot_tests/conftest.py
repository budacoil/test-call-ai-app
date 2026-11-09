from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from spritepilot.settings import Settings
from spritepilot.storage import Store


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path)
    yield value
    value.close()
