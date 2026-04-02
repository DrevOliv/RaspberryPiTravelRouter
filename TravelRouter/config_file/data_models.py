from pydantic import BaseModel, Field


class AuthData(BaseModel):
    password_salt: str = ""
    password_hash: str = ""
    password_updated_at: float | None = None


class DataModels(BaseModel):
    auth: AuthData = Field(default_factory=AuthData)
