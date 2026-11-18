from __future__ import annotations

import pytest
from helpers import OPEN_STORES, run


@pytest.fixture(autouse=True)
def close_stores():
    """Close every store a test opened, so a server never holds one connection pool per finished test.

    @return (Iterator[None]): control to the test.
    """
    yield
    while OPEN_STORES:
        run(OPEN_STORES.pop().close())
