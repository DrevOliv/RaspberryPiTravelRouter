import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException, Request, Response, status

from TravelRouter.config_file import DataManager
from TravelRouter.config_file.data_models import AuthData

DEFAULT_COOKIE_NAME = "tr_session"
DEFAULT_SESSION_TTL_SECONDS = 24 * 60 * 60
DEFAULT_TEMP_PASSWORD = "changeme"
MIN_PASSWORD_LENGTH = 12
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SessionRecord:
    expires_at: float


class AuthManager:
    def __init__(self) -> None:
        self.data_manager = DataManager()
        self.cookie_name = os.getenv("TRAVELROUTER_AUTH_COOKIE_NAME", DEFAULT_COOKIE_NAME)
        self.session_ttl_seconds = int(
            os.getenv("TRAVELROUTER_AUTH_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS)
        )
        self.secure_cookie = _env_flag("TRAVELROUTER_AUTH_SECURE_COOKIE", default=False)
        self._lock = Lock()
        self._sessions: dict[str, SessionRecord] = {}

    def hash_password(self, password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=SCRYPT_DKLEN,
        )

    def build_auth_data(self, password: str) -> AuthData:
        salt = secrets.token_bytes(16)
        password_hash = self.hash_password(password, salt)
        return AuthData(
            password_salt=base64.b64encode(salt).decode("ascii"),
            password_hash=base64.b64encode(password_hash).decode("ascii"),
            password_updated_at=time.time(),
        )

    def _get_auth_data(self) -> AuthData:
        return self.data_manager.get_data().auth

    def _set_auth_data(self, auth_data: AuthData) -> None:
        data = self.data_manager.get_data()
        data.auth = auth_data
        self.data_manager.set_data(data)

    def has_password(self, auth_data: AuthData | None = None) -> bool:
        active_auth_data = auth_data or self._get_auth_data()
        return bool(active_auth_data.password_salt and active_auth_data.password_hash)

    def verify_password(self, password: str, auth_data: AuthData | None = None) -> bool:
        active_auth_data = auth_data or self._get_auth_data()
        if not self.has_password(active_auth_data):
            return False

        salt = base64.b64decode(active_auth_data.password_salt)
        stored_hash = base64.b64decode(active_auth_data.password_hash)
        password_hash = self.hash_password(password, salt)
        return hmac.compare_digest(password_hash, stored_hash)

    def ensure_auth_data(self) -> None:
        auth_data = self._get_auth_data()
        if self.has_password(auth_data):
            return

        self._set_auth_data(self.build_auth_data(DEFAULT_TEMP_PASSWORD))

    def login(self, password: str, response: Response) -> None:
        if not self.verify_password(password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password",
            )

        self.set_session_cookie(response, self.create_session())

    def logout(self, request: Request, response: Response) -> None:
        self.revoke_session(self.get_session_token(request))
        self.clear_session_cookie(response)

    def change_password(self, current_password: str, new_password: str, response: Response) -> None:
        if not self.verify_password(current_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )

        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"New password must be at least {MIN_PASSWORD_LENGTH} characters long",
            )

        if hmac.compare_digest(current_password, new_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be different from the current password",
            )

        self._set_auth_data(self.build_auth_data(new_password))
        self.revoke_all_sessions()
        self.clear_session_cookie(response)

    def require_api_auth(self, request: Request) -> None:
        if not self.has_session(self.get_session_token(request)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )

    def get_session_token(self, request: Request) -> str | None:
        return request.cookies.get(self.cookie_name)

    def create_session(self) -> str:
        with self._lock:
            self._cleanup_expired_sessions()
            token = secrets.token_urlsafe(32)
            self._sessions[token] = SessionRecord(expires_at=time.time() + self.session_ttl_seconds)
            return token

    def has_session(self, token: str | None) -> bool:
        if not token:
            return False

        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return False
            if session.expires_at <= time.time():
                self._sessions.pop(token, None)
                return False
            return True

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return

        with self._lock:
            self._sessions.pop(token, None)

    def revoke_all_sessions(self) -> None:
        with self._lock:
            self._sessions.clear()

    def set_session_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            key=self.cookie_name,
            value=token,
            httponly=True,
            max_age=self.session_ttl_seconds,
            path="/",
            samesite="strict",
            secure=self.secure_cookie,
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(
            key=self.cookie_name,
            httponly=True,
            path="/",
            samesite="strict",
            secure=self.secure_cookie,
        )

    def _cleanup_expired_sessions(self) -> None:
        now = time.time()
        expired_tokens = [token for token, session in self._sessions.items() if session.expires_at <= now]
        for token in expired_tokens:
            self._sessions.pop(token, None)
