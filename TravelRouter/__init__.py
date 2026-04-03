from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from TravelRouter.components.auth import auth_api
from TravelRouter.components.auth.auth import AuthManager
from TravelRouter.config_file import DataManager
from TravelRouter.helpers import ApiResponse, build_api_response, dump_api_response

APP_TITLE = "Pi Travel Router API"
APP_DESCRIPTION = (
    "API for the Pi Travel Router web UI, including Wi-Fi, Tailscale, Jellyfin, "
    "playback control, and rsync backups."
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
    {"name": "rsync", "description": "Drive discovery and rsync backup job management."},
]


def _json_api_response(status_code: int, msg, success: bool) -> JSONResponse:
    response = build_api_response(msg=msg, success=success)
    return JSONResponse(status_code=status_code, content=dump_api_response(response))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return _json_api_response(exc.status_code, exc.detail, False)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _json_api_response(422, exc.errors(), False)

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(_: Request, __: Exception) -> JSONResponse:
        return _json_api_response(500, "Internal server error", False)


def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_TITLE,
        description=APP_DESCRIPTION,
        version=APP_VERSION,
        openapi_tags=OPENAPI_TAGS,
    )

    auth_manager = AuthManager()
    auth_manager.ensure_auth_data()

    app.state.auth_manager = auth_manager

    app.include_router(auth_api)
    register_exception_handlers(app)

    return app
