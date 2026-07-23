"""MomiHelm authenticated browser gateway and organization policy boundary."""

from __future__ import annotations

import hashlib
import os
import secrets
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Annotated

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

from database import (
    Principal,
    create_owner,
    create_session,
    create_user,
    delete_session,
    get_session_user,
    get_user_by_email,
    get_user_by_id,
    list_users,
    setup_required,
    update_password_and_revoke_sessions,
    update_policy_mode,
)


SERVICE_NAME = "gateway-service"
SESSION_COOKIE = "momihelm_session"
N8N_BASE_URL = os.environ.get("MOMIHELM_N8N_INTERNAL_URL", "http://n8n:5678")
SESSION_TTL_SECONDS = int(
    float(os.environ.get("MOMIHELM_SESSION_TTL_HOURS", "12")) * 3600
)
COOKIE_SECURE = os.environ.get("MOMIHELM_COOKIE_SECURE", "false").lower() == "true"
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get(
        "MOMIHELM_ALLOWED_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
}
MAX_PROMPT_CHARS = int(os.environ.get("MOMIHELM_MAX_PROMPT_CHARS", "100000"))
MAX_IMAGE_BASE64_CHARS = int(
    os.environ.get("MOMIHELM_MAX_IMAGE_BASE64_CHARS", "7000000")
)

password_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
)

app = FastAPI(title="MomiHelm Gateway")


class SetupRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    organization_name: str = Field(min_length=2, max_length=100)
    department_id: str = Field(default="general", min_length=1, max_length=80)

    @field_validator("display_name", "organization_name", "department_id")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return " ".join(value.split())


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class PolicyUpdateRequest(BaseModel):
    policy_mode: str

    @field_validator("policy_mode")
    @classmethod
    def normalize_policy_mode(cls, value: str) -> str:
        mode = value.strip().lower()
        if mode not in {"conservative", "balanced", "aggressive"}:
            raise ValueError("invalid policy mode")
        return mode


class CreateUserRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    role: str = "member"
    department_id: str = Field(default="general", min_length=1, max_length=80)

    @field_validator("display_name", "department_id")
    @classmethod
    def trim_user_text(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        role = value.strip().lower()
        if role not in {"admin", "member"}:
            raise ValueError("role must be admin or member")
        return role


class UserResponse(BaseModel):
    id: str
    organization_id: str
    organization_name: str
    email: EmailStr
    display_name: str
    role: str
    department_id: str
    policy_mode: str
    can_manage: bool


class AuthStateResponse(BaseModel):
    setup_required: bool
    authenticated: bool
    user: UserResponse | None = None


def _user_response(principal: Principal) -> UserResponse:
    return UserResponse(
        id=principal.id,
        organization_id=principal.organization_id,
        organization_name=principal.organization_name,
        email=principal.email,
        display_name=principal.display_name,
        role=principal.role,
        department_id=principal.department_id,
        policy_mode=principal.policy_mode,
        can_manage=principal.can_manage,
    )


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_session(principal: Principal, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    create_session(
        _hash_session_token(token),
        principal.id,
        ttl_seconds=SESSION_TTL_SECONDS,
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        path="/",
    )


def _optional_user(request: Request) -> Principal | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return get_session_user(_hash_session_token(token))


def require_user(request: Request) -> Principal:
    principal = _optional_user(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication_required")
    return principal


CurrentUser = Annotated[Principal, Depends(require_user)]


def require_manager(user: CurrentUser) -> Principal:
    if not user.can_manage:
        raise HTTPException(status_code=403, detail="manager_role_required")
    return user


ManagerUser = Annotated[Principal, Depends(require_manager)]


class LoginRateLimiter:
    def __init__(self, attempts: int = 5, window_seconds: int = 900):
        self.attempts = attempts
        self.window_seconds = window_seconds
        self.events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        events = self.events[key]
        while events and now - events[0] >= self.window_seconds:
            events.popleft()
        if len(events) >= self.attempts:
            raise HTTPException(status_code=429, detail="too_many_login_attempts")

    def fail(self, key: str) -> None:
        self.events[key].append(time.monotonic())

    def clear(self, key: str) -> None:
        self.events.pop(key, None)


login_limiter = LoginRateLimiter()


@app.middleware("http")
async def security_boundary(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and origin not in ALLOWED_ORIGINS:
            return JSONResponse(status_code=403, content={"detail": "untrusted_origin"})
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/auth/state", response_model=AuthStateResponse)
def auth_state(request: Request):
    principal = _optional_user(request)
    return AuthStateResponse(
        setup_required=setup_required(),
        authenticated=principal is not None,
        user=_user_response(principal) if principal else None,
    )


@app.post("/auth/setup", response_model=AuthStateResponse, status_code=201)
def auth_setup(payload: SetupRequest, response: Response):
    if not setup_required():
        raise HTTPException(status_code=409, detail="setup_already_completed")
    try:
        principal = create_owner(
            email=str(payload.email).strip().lower(),
            display_name=payload.display_name,
            organization_name=payload.organization_name,
            department_id=payload.department_id.lower().replace(" ", "-"),
            password_hash=password_hasher.hash(payload.password),
        )
    except ValueError as exc:
        if str(exc) == "setup_already_completed":
            raise HTTPException(
                status_code=409,
                detail="setup_already_completed",
            ) from exc
        raise
    _new_session(principal, response)
    return AuthStateResponse(
        setup_required=False,
        authenticated=True,
        user=_user_response(principal),
    )


@app.post("/auth/login", response_model=AuthStateResponse)
def auth_login(payload: LoginRequest, request: Request, response: Response):
    email = str(payload.email).strip().lower()
    client_host = request.client.host if request.client else "unknown"
    rate_key = f"{client_host}:{email}"
    login_limiter.check(rate_key)
    record = get_user_by_email(email)
    if record is None:
        login_limiter.fail(rate_key)
        raise HTTPException(status_code=401, detail="invalid_credentials")
    principal, password_hash = record
    try:
        password_hasher.verify(password_hash, payload.password)
    except (VerifyMismatchError, InvalidHashError):
        login_limiter.fail(rate_key)
        raise HTTPException(status_code=401, detail="invalid_credentials")
    login_limiter.clear(rate_key)
    _new_session(principal, response)
    return AuthStateResponse(
        setup_required=False,
        authenticated=True,
        user=_user_response(principal),
    )


@app.post("/auth/logout", status_code=204)
def auth_logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        delete_session(_hash_session_token(token))
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="strict",
    )
    return response


@app.get("/auth/me", response_model=UserResponse)
def auth_me(user: CurrentUser):
    return _user_response(user)


@app.put("/auth/password", response_model=UserResponse)
def change_password(
    payload: PasswordChangeRequest,
    response: Response,
    user: CurrentUser,
):
    record = get_user_by_email(user.email)
    if record is None:
        raise HTTPException(status_code=401, detail="authentication_required")
    _, password_hash = record
    try:
        password_hasher.verify(password_hash, payload.current_password)
    except (VerifyMismatchError, InvalidHashError):
        raise HTTPException(status_code=401, detail="invalid_current_password")
    try:
        password_hasher.verify(password_hash, payload.new_password)
    except VerifyMismatchError:
        pass
    else:
        raise HTTPException(status_code=422, detail="new_password_must_differ")
    update_password_and_revoke_sessions(
        user.id,
        password_hasher.hash(payload.new_password),
    )
    _new_session(user, response)
    return _user_response(user)


@app.put("/policy", response_model=UserResponse)
def update_policy(payload: PolicyUpdateRequest, user: ManagerUser):
    update_policy_mode(user.organization_id, payload.policy_mode)
    refreshed = get_session_user_for_refresh(user.id)
    return _user_response(refreshed)


@app.get("/users", response_model=list[UserResponse])
def organization_users(user: ManagerUser):
    return [
        _user_response(principal)
        for principal in list_users(user.organization_id)
    ]


@app.post("/users", response_model=UserResponse, status_code=201)
def add_organization_user(payload: CreateUserRequest, user: ManagerUser):
    if payload.role == "admin" and user.role != "owner":
        raise HTTPException(status_code=403, detail="owner_role_required")
    try:
        principal = create_user(
            organization_id=user.organization_id,
            email=str(payload.email).strip().lower(),
            display_name=payload.display_name,
            department_id=payload.department_id.lower().replace(" ", "-"),
            role=payload.role,
            password_hash=password_hasher.hash(payload.password),
        )
    except ValueError as exc:
        if str(exc) == "email_already_exists":
            raise HTTPException(
                status_code=409,
                detail="email_already_exists",
            ) from exc
        raise
    return _user_response(principal)


def get_session_user_for_refresh(user_id: str) -> Principal:
    principal = get_user_by_id(user_id)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication_required")
    return principal


async def _upstream_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> Response:
    timeout = httpx.Timeout(190.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            upstream = await client.request(
                method,
                f"{N8N_BASE_URL}{path}",
                json=payload,
                params=params,
            )
    except httpx.HTTPError as exc:
        return JSONResponse(
            status_code=502,
            content={"detail": "workflow_unavailable", "message": str(exc)},
        )
    content_type = upstream.headers.get("content-type", "application/json")
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={"Content-Type": content_type},
    )


@app.post("/webhook/tokenwise")
async def run_momihelm(request: Request, user: CurrentUser):
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="request_body_must_be_object")
    prompt = body.get("prompt", "")
    if not isinstance(prompt, str):
        raise HTTPException(status_code=422, detail="prompt_must_be_text")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise HTTPException(status_code=413, detail="prompt_too_large")
    image_base64 = body.get("image_base64")
    if image_base64 is not None and (
        not isinstance(image_base64, str)
        or len(image_base64) > MAX_IMAGE_BASE64_CHARS
    ):
        raise HTTPException(status_code=413, detail="image_too_large")

    trusted_body = dict(body)
    trusted_body.update(
        {
            "request_id": f"r-{uuid.uuid4().hex}",
            "organization_id": user.organization_id,
            "user_id": user.id,
            "dept_id": user.department_id,
            "policy_mode": user.policy_mode,
        }
    )
    return await _upstream_request(
        "POST",
        "/webhook/tokenwise",
        payload=trusted_body,
    )


@app.get("/webhook/tokenwise-usage-summary")
async def usage_summary(
    user: CurrentUser,
    period_days: int = Query(default=30, ge=1, le=365),
    dept_id: str | None = Query(default=None, max_length=80),
    operating_cost_usd: float | None = Query(default=None, ge=0),
):
    params: dict[str, Any] = {
        "period_days": period_days,
        "organization_id": user.organization_id,
    }
    if user.can_manage:
        params["include_legacy"] = "true"
        if dept_id:
            params["dept_id"] = dept_id
    else:
        params["user_id"] = user.id
    if operating_cost_usd is not None:
        params["operating_cost_usd"] = operating_cost_usd
    return await _upstream_request(
        "GET",
        "/webhook/tokenwise-usage-summary",
        params=params,
    )
