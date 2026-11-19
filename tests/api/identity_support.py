"""A TestClient over the real app, container and use cases, with port doubles."""

from fastapi.testclient import TestClient

from insumap.container import Container
from insumap.infrastructure.platform_adapters import PlatformAdapters
from insumap.main import create_app
from tests.support.commands import InMemoryAuditLog
from tests.support.identity_world import IdentityWorld
from tests.support.settings import make_settings

ORIGIN = "https://app.example.test"
CSRF_HEADERS = {"X-Requested-With": "insumap-web"}


class IdentityApi:
    """The app, its client (https, so ``Secure`` cookies round trip) and the doubles."""

    def __init__(self) -> None:
        self.world = IdentityWorld()
        self.audit_log = InMemoryAuditLog()
        settings = make_settings(cors_origins=[ORIGIN])
        container = Container(
            settings,
            clock=self.world.clock,
            identity_adapters=self.world.adapters(),
            platform_adapters=PlatformAdapters(audit_log=self.audit_log),
        )
        self.app = create_app(container)
        self.client = TestClient(
            self.app, base_url="https://testserver", raise_server_exceptions=False
        )

    def bearer(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}
