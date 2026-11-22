from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("LIFEOS_BACKGROUND_SYNC", "0")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from lifeos.db import Base, SessionLocal, create_all, get_engine, init_engine  # noqa: E402
from lifeos.models import Device  # noqa: E402
from lifeos.seed import seed_defaults  # noqa: E402
from lifeos.services.settings import update_settings  # noqa: E402

TZ = "America/Chicago"


@pytest.fixture()
def db() -> Iterator[Session]:
    init_engine(":memory:")
    create_all()
    s = SessionLocal()
    seed_defaults(s)
    update_settings(s, {"timezone": TZ})
    # Deterministic device id regardless of the test machine's hostname.
    for d in s.query(Device).all():
        s.delete(d)
    s.add(Device(id="personal-mac", name="Personal Mac", kind="mac", monitoring_approved=True))
    s.commit()
    yield s
    s.close()
    Base.metadata.drop_all(get_engine())


@pytest.fixture()
def client(db: Session) -> Iterator[TestClient]:
    from lifeos.main import app

    app.state.skip_init = True
    with TestClient(app) as c:
        yield c
