from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    success: bool = False
    msg: Any = ""
    msg_type: str = "string"


def build_api_response(msg: Any = "", success: bool = True, msg_type: str | None = None) -> ApiResponse:
    if msg_type is None:
        msg_type = "json" if isinstance(msg, (dict, list)) else "string"
    return ApiResponse(success=success, msg=msg, msg_type=msg_type)


def build_api_response_json(msg: Any = None, success: bool = True) -> ApiResponse:
    return build_api_response(msg=msg, success=success, msg_type="json")


def dump_api_response(response: ApiResponse) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    return response.dict()
