import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SLOW_CREATE_SECONDS", "0")
# Tests must never send real email, whatever is set in the developer's shell.
for _var in ("BREVO_API_KEY", "MAIL_FROM", "MAIL_FROM_NAME", "PUBLIC_BASE_URL"):
    os.environ.pop(_var, None)

from fastapi.testclient import TestClient  # noqa: E402

from app import clock, db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import reset_data  # noqa: E402

# Freeze "now" at 10:00 am IST so pickup-slot tests are deterministic.
FROZEN_NOW = datetime(2026, 11, 6, 10, 0)


@pytest.fixture()
def client(tmp_path):
    db.reset_connection(str(tmp_path / "test.db"))
    clock.freeze(FROZEN_NOW)
    reset_data()
    with TestClient(app) as c:
        yield c
    clock.freeze(None)
