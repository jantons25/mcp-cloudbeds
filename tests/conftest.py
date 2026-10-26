from zoneinfo import ZoneInfo

import keyring
import pytest
from keyring.backend import KeyringBackend

from cloudbeds_mcp.config import Settings

FAKE_KEY = "cbat_TESTKEY_no_es_real_123"


class FakeSleep:
    """Reemplaza asyncio.sleep: registra las esperas sin dormir de verdad."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class MemoryKeyring(KeyringBackend):
    """Keyring en memoria: los tests nunca tocan el Administrador de credenciales real."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture(autouse=True)
def memory_keyring():
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        api_key=FAKE_KEY,
        property_id="12345",
        show_pii=False,
        tz=ZoneInfo("America/Lima"),
        max_results=500,
    )


@pytest.fixture
def fake_sleep() -> FakeSleep:
    return FakeSleep()
