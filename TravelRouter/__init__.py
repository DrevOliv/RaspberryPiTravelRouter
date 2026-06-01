import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from TravelRouter.components.auth import auth_api, require_api_auth
from TravelRouter.components.auth.auth import AuthManager
from TravelRouter.components.drive import router as drive_router
from TravelRouter.components.rsync import router as rsync_router
from TravelRouter.components.rsync.system_api import job_manager
from TravelRouter.components.settings import router as settings_router
from TravelRouter.components.tailscale import router as tailscale_router
from TravelRouter.components.wifi import router as wifi_router
from TravelRouter.config_file import DataManager
from TravelRouter.helpers import ApiResponse, build_api_response, dump_api_response

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

_pages_router = APIRouter()


@_pages_router.get("/", include_in_schema=False)
async def _serve_index() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@_pages_router.get("/login", include_in_schema=False)
async def _serve_login() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "login.html"))


@_pages_router.get("/settings-page", include_in_schema=False)
async def _serve_settings_page() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "settings.html"))


@_pages_router.get("/drives-page", include_in_schema=False)
async def _serve_drives_page() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "drives.html"))


@_pages_router.get(
    "/api/health",
    response_model=ApiResponse,
    tags=["meta"],
    summary="Health check",
    description="Check that the backend API is running.",
)
async def _health_check() -> ApiResponse:
    return ApiResponse(success=True, msg="ok")


APP_TITLE = "Pi Travel Router API"
APP_DESCRIPTION = (
    "API for the Pi Travel Router web UI, including Wi-Fi, Tailscale, Jellyfin, "
    "playback control, and drive backups."
)
APP_VERSION = "1.0.0"
OPENAPI_TAGS = [
    {"name": "auth", "description": "Authentication endpoints for the admin session."},
    {"name": "meta", "description": "App-level metadata and environment information."},
    {"name": "home", "description": "Home dashboard data and upstream Wi-Fi actions."},
    {"name": "settings", "description": "Wi-Fi, Tailscale, and Jellyfin configuration endpoints."},
    {"name": "wifi", "description": "Wi-Fi connection, QR, and access-point configuration actions."},
    {"name": "tailscale", "description": "Tailscale exit-node selection and toggle actions."},
    {"name": "media", "description": "Jellyfin browsing and playback start endpoints."},
    {"name": "remote", "description": "Playback transport and track-selection controls."},
    {"name": "playback", "description": "Playback transport and track-selection control APIs."},
    {"name": "drive", "description": "Drive discovery and drive backup job management."},
    {"name": "rsync", "description": "Rsync job control and live transfer progress streaming."},
]


def _json_api_response(status_code: int, msg, success: bool) -> JSONResponse:
    response = build_api_response(msg=msg, success=success)
    return JSONResponse(status_code=status_code, content=dump_api_response(response))


def register_exception_handlers(app: FastAPI) -> None:
    async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _json_api_response(exc.status_code, exc.detail, False)

    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _json_api_response(422, exc.errors(), False)

    async def unexpected_exception_handler(_: Request, __: Exception) -> JSONResponse:
        return _json_api_response(500, "Internal server error", False)

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        yield
    finally:
        await job_manager.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_TITLE,
        description=APP_DESCRIPTION,
        version=APP_VERSION,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )

    auth_manager = AuthManager()
    auth_manager.ensure_auth_data()

    app.state.auth_manager = auth_manager

    # Login/logout must stay public; every other API router requires an
    # authenticated session. Enforcing it here keeps new routes protected by
    # default instead of relying on each route to remember the dependency.
    auth_required = [Depends(require_api_auth)]

    app.include_router(_pages_router)
    app.include_router(auth_api)
    app.include_router(drive_router, dependencies=auth_required)
    app.include_router(rsync_router, dependencies=auth_required)
    app.include_router(settings_router, dependencies=auth_required)
    app.include_router(tailscale_router, dependencies=auth_required)
    app.include_router(wifi_router, dependencies=auth_required)
    register_exception_handlers(app)

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    return app


