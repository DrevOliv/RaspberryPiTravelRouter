from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    success: bool = False
    msg: Any = ""
    msg_type: str = "string"


def build_api_response_json(msg: Any = None, success: bool = True) -> ApiResponse:
    return ApiResponse(success=success, msg=msg, msg_type="json")


def dump_api_response(response: ApiResponse) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    return response.dict()
