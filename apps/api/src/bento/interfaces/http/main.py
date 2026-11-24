import os
from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bento.adapters.sync import configure_change_capture
from bento.infrastructure.settings import Settings, get_settings, settings_database_path
from bento.interfaces.desktop.routes import router as desktop_router
from bento.interfaces.desktop.security import DesktopSecurityConfig, DesktopSecurityMiddleware
from bento.interfaces.http.request_guard import LocalRequestGuard, allowed_hosts_from_environ, api_token_from_environ
from bento.interfaces.http.routes import router


def create_app(
    settings: Settings | None = None,
    *,
    desktop_environ: Mapping[str, str] | None = None,
    guard_environ: Mapping[str, str] | None = None,
    openapi: bool = True,
) -> FastAPI:
    """`guard_environ` replaces `os.environ` for the headless request guard (embedded hosts pass their own
    configuration); `openapi=False` serves no schema or docs (the schema is exported at build time)."""
    resolved_settings = settings or get_settings()
    configure_change_capture(resolved_settings.storage_backend != "local")
    schema = {} if openapi else {"openapi_url": None, "docs_url": None, "redoc_url": None}
    app = FastAPI(title=resolved_settings.app_name, version=resolved_settings.app_version, **schema)
    app.state.settings = resolved_settings
    app.state.settings_database_path = settings_database_path(resolved_settings)

    web_port = resolved_settings.web_port
    allowed_origins = [f"http://127.0.0.1:{web_port}", f"http://localhost:{web_port}"]
    if resolved_settings.runtime_mode == "desktop":
        security = DesktopSecurityConfig.from_environ(os.environ if desktop_environ is None else desktop_environ)
        allowed_origins = [security.origin]
        app.add_middleware(DesktopSecurityMiddleware, config=security)
    else:
        # Inside CORS, so the web client can still read these rejections.
        guard = os.environ if guard_environ is None else guard_environ
        app.add_middleware(
            LocalRequestGuard,
            allowed_hosts=allowed_hosts_from_environ(guard),
            api_token=api_token_from_environ(guard),
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")
    app.include_router(desktop_router, prefix="/api/desktop", include_in_schema=False)
    return app


def __getattr__(name: str) -> FastAPI:
    # `uvicorn bento.interfaces.http.main:app` keeps working, but importing this module no longer builds an app
    # (and reads settings) as a side effect.
    if name == "app":
        return create_app()
    raise AttributeError(name)


def main() -> None:
    from bento.interfaces.desktop.launcher import main as launcher_main

    launcher_main(("api",))


if __name__ == "__main__":
    main()
