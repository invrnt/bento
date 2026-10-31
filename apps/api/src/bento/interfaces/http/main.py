import os
from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    app = FastAPI(title=resolved_settings.app_name, version=resolved_settings.app_version)
    app.state.settings = resolved_settings
    app.state.settings_database_path = settings_database_path(resolved_settings)

    web_port = resolved_settings.web_port
    allowed_origins = [f"http://127.0.0.1:{web_port}", f"http://localhost:{web_port}"]
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
