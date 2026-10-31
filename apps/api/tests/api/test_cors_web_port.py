from fastapi.testclient import TestClient

from bento.infrastructure.settings import Settings
from bento.interfaces.http.main import create_app


def test_cors_allows_the_configured_web_port(tmp_path) -> None:
    app = create_app(Settings(data_dir=str(tmp_path), web_port=5174))
    client = TestClient(app)

    allowed = client.options(
        "/api/health",
        headers={"Origin": "http://127.0.0.1:5174", "Access-Control-Request-Method": "GET"},
    )
    blocked = client.options(
        "/api/health",
        headers={"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "GET"},
    )

    assert allowed.headers.get("access-control-allow-origin") == "http://127.0.0.1:5174"
    assert "access-control-allow-origin" not in blocked.headers
