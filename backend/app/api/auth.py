"""注册 / 登录 / 退出 / 当前身份。

令牌只在注册与登录的响应里下发一次，之后所有请求走 Authorization: Bearer。
密码校验是 CPU 密集的 scrypt，端点用同步 def 让 FastAPI 丢到线程池，不卡事件循环。
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import bearer_token, current_user

router = APIRouter()


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def _session(request: Request, user: dict) -> dict:
    token, expires_at = request.app.state.accounts.issue(user["user_id"])
    return {"token": token, "expires_at": expires_at, "user": user}


@router.post("/api/auth/register", status_code=201)
def register(body: Credentials, request: Request):
    try:
        user = request.app.state.accounts.register(body.username, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if user is None:
        raise HTTPException(409, "这个用户名已经被注册了")
    return _session(request, user)


@router.post("/api/auth/login")
def login(body: Credentials, request: Request):
    throttle = request.app.state.login_throttle
    wait = throttle.blocked_for(body.username)
    if wait:
        raise HTTPException(429, f"尝试次数过多，请 {wait} 秒后再试")
    user = request.app.state.accounts.verify(body.username, body.password)
    if user is None:
        throttle.record_failure(body.username)
        # 不区分「用户名不存在」与「密码错」，免得拿登录接口枚举账号
        raise HTTPException(401, "用户名或密码不正确")
    throttle.reset(body.username)
    return _session(request, user)


@router.post("/api/auth/logout")
def logout(request: Request, user: str = Depends(current_user)):
    request.app.state.accounts.revoke(bearer_token(request))
    return {"ok": True, "user_id": user}


@router.get("/api/auth/me")
def me(request: Request):
    """令牌失效不抛 401：前端据此清掉本地令牌、回到未登录态，而不是弹一堵登录墙。"""
    token = bearer_token(request)
    accounts = request.app.state.accounts
    user_id = accounts.user_for_token(token) if token else None
    user = accounts.get_user(user_id) if user_id else None
    return {"user": user, "guest": user is None, "expired": bool(token) and user is None}
