from fastapi import Request

from TravelRouter.components.auth.auth import AuthManager


def get_auth_manager(request: Request) -> AuthManager:
    return request.app.state.auth_manager


def require_api_auth(request: Request) -> None:
    get_auth_manager(request).require_api_auth(request)
