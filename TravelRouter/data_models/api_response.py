from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    success: bool = True
    msg: Any = None


def build_api_response(msg: Any = None, success: bool = True) -> ApiResponse:
    return ApiResponse(success=success, msg=msg)


def dump_api_response(response: ApiResponse) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    return response.dict()
