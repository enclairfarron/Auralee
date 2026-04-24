from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def test_client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as client:
        yield client
