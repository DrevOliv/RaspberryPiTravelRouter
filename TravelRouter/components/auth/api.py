from fastapi import APIRouter, Depends, Request, Response

from TravelRouter.components.auth.functions import get_auth_manager, require_api_auth
from TravelRouter.components.auth.models import ChangePasswordRequest, LoginRequest
from TravelRouter.helpers import ApiResponse, build_api_response

auth_api = APIRouter(prefix="/api/auth", tags=["auth"])


@auth_api.post("/login",
               response_model=ApiResponse
               )
def login_api(payload: LoginRequest, request: Request, response: Response) -> ApiResponse:
    get_auth_manager(request).login(payload.password, response)
    return build_api_response({"authenticated": True})


@auth_api.post("/logout", response_model=ApiResponse)
def logout_api(request: Request, response: Response) -> ApiResponse:
    get_auth_manager(request).logout(request, response)
    return build_api_response("Logged out")


@auth_api.post(
    "/change-password",
    response_model=ApiResponse,
    dependencies=[Depends(require_api_auth)],
)
def change_password_api(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
) -> ApiResponse:
    get_auth_manager(request).change_password(payload.current_password, payload.new_password, response)
    return build_api_response({"password_changed": True})


@auth_api.get("/session", response_model=ApiResponse, dependencies=[Depends(require_api_auth)])
def session_api() -> ApiResponse:
    return build_api_response({"authenticated": True})
