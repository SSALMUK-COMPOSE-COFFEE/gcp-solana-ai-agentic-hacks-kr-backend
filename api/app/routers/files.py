import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from app.core.config import settings
from app.core.storage import EXTENSIONS

router = APIRouter(prefix="/static", tags=["static"])

FILE_NOT_FOUND = "존재하지 않는 파일입니다."

MEDIA_TYPES = {extension: mime for mime, extension in EXTENSIONS.items()} | {".svg": "image/svg+xml"}
NAME_PATTERN = re.compile(rf"^[0-9a-f]{{32}}({'|'.join(re.escape(e) for e in EXTENSIONS.values())})$")

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
SERVICE_ASSETS = {"icon.png", "icon.svg", "icon.webp"}


@router.get("/{name}")
async def read_file(name: str):
    if name in SERVICE_ASSETS:
        asset = ASSET_DIR / name
        if not asset.is_file():
            raise HTTPException(status_code=404, detail=FILE_NOT_FOUND)
        return FileResponse(asset, media_type=MEDIA_TYPES[asset.suffix])

    if not NAME_PATTERN.match(name):
        raise HTTPException(status_code=404, detail=FILE_NOT_FOUND)

    if settings.storage_backend != "local":
        return RedirectResponse(f"{settings.storage_public_base_url.rstrip('/')}/{name}")

    path = Path(settings.storage_dir) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=FILE_NOT_FOUND)

    return FileResponse(
        path,
        media_type=MEDIA_TYPES[path.suffix],
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )
