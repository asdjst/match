import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import current_user
from core.schemas.food import FoodAnalysis

router = APIRouter()

MAX_IMAGE_BYTES = 8 * 1024 * 1024
_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_IMAGE_ID = re.compile(r"^[0-9a-f]{32}$")
_SUFFIXES = (".jpg", ".png", ".webp")


def _suffix_for(data: bytes) -> str | None:
    """按文件头判类型，不信任客户端给的 filename/content-type。"""
    if data.startswith(_JPEG):
        return ".jpg"
    if data.startswith(_PNG):
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


@router.post("/api/food/analyze", response_model=FoodAnalysis, dependencies=[Depends(current_user)])
async def analyze_food(request: Request, file: UploadFile = File(...)) -> FoodAnalysis:
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "图片超过 8MB")
    suffix = _suffix_for(data)
    if suffix is None:
        raise HTTPException(415, "只支持 JPG/PNG/WebP 图片")

    image_id = uuid.uuid4().hex
    upload_dir = Path(request.app.state.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{image_id}{suffix}"
    path.write_bytes(data)

    return await run_in_threadpool(request.app.state.food_analyzer.analyze, image_id, path)


@router.get("/api/food/images/{image_id}")
async def get_food_image(image_id: str, request: Request) -> FileResponse:
    """回放餐盘照片：只接受本服务生成的 32 位随机 ID，不接受任意路径。
    ID 是 128 位随机值且只经归属校验后的接口下发，故此处按能力 URL 处理——<img> 带不了令牌。"""
    if not _IMAGE_ID.fullmatch(image_id):
        raise HTTPException(404, "图片不存在")
    upload_dir = Path(request.app.state.upload_dir)
    for suffix in _SUFFIXES:
        path = upload_dir / f"{image_id}{suffix}"
        if path.is_file():
            return FileResponse(
                path,
                headers={"Cache-Control": "private, max-age=31536000, immutable"},
            )
    raise HTTPException(404, "图片不存在")
