import os
from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bento.adapters.sync import configure_change_capture
from bento.infrastructure.settings import Settings, get_settings, settings_database_path
from bento.interfaces.desktop.routes import router as desktop_router
from bento.interfaces.desktop.security import DesktopSecurityConfig, DesktopSecurityMiddleware
from bento.interfaces.http.routes import router


def create_app(
    settings: Settings | None = None,
    *,
    desktop_environ: Mapping[str, str] | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_change_capture(resolved_settings.storage_backend != "local")
    app = FastAPI(title=resolved_settings.app_name, version=resolved_settings.app_version)
    app.state.settings = resolved_settings
    app.state.settings_database_path = settings_database_path(resolved_settings)

    allowed_origins = ["http://127.0.0.1:5173", "http://localhost:5173"]
    if resolved_settings.runtime_mode == "desktop":
        security = DesktopSecurityConfig.from_environ(os.environ if desktop_environ is None else desktop_environ)
        allowed_origins = [security.origin]
        app.add_middleware(DesktopSecurityMiddleware, config=security)

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


app = create_app()


def main() -> None:
    from bento.interfaces.desktop.launcher import main as launcher_main

    launcher_main(("api",))


if __name__ == "__main__":
    main()
