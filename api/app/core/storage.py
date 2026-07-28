from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import settings

UNSUPPORTED_TYPE = "지원하지 않는 파일 형식입니다. PDF 또는 이미지만 업로드할 수 있습니다."
TOO_LARGE = "파일이 너무 큽니다."
BACKEND_UNAVAILABLE = "파일 저장소를 사용할 수 없습니다."

EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def _local_dir() -> Path:
    directory = Path(settings.storage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def public_url(name: str) -> str:
    return f"{settings.storage_public_base_url.rstrip('/')}/{name}"


def save(content: bytes, content_type: str) -> str:
    extension = EXTENSIONS.get((content_type or "").split(";")[0].strip())
    if extension is None:
        raise HTTPException(status_code=400, detail=UNSUPPORTED_TYPE)
    if len(content) > settings.storage_max_bytes:
        raise HTTPException(status_code=413, detail=TOO_LARGE)

    if settings.storage_backend != "local":
        raise HTTPException(status_code=503, detail=BACKEND_UNAVAILABLE)

    name = f"{uuid4().hex}{extension}"
    (_local_dir() / name).write_bytes(content)
    return public_url(name)
