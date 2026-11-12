"""接口身份：登录令牌 → 用户ID；没带令牌就是单机演示身份 local。

所有个人数据读写都以这里解析出的用户为准，不信请求体里的 user_id。
"""

from fastapi import HTTPException, Request


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header[:7].lower() == "bearer " else ""


def current_user(request: Request) -> str:
    token = bearer_token(request)
    if not token:
        return "local"
    user_id = request.app.state.accounts.user_for_token(token)
    if user_id is None:
        raise HTTPException(401, "登录已过期或无效，请重新登录")
    return user_id
