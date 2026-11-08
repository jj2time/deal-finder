import copy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cfg(tmp_path):
    with open(ROOT / "config.example.yaml") as f:
        c = yaml.safe_load(f)
    c = copy.deepcopy(c)
    c["database"] = str(tmp_path / "test.sqlite3")
    c["areas"]["postcode_districts"] = []
    return c
