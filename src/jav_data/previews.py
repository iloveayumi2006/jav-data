"""Small, reusable library previews; original covers are never modified."""

import hashlib
import os
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageOps

_locks = [threading.Lock() for _ in range(16)]


def cover_preview(source: Path, data_dir: Path, asset_id: int) -> Path:
    stat = source.stat()
    version = hashlib.sha256(f"{source}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[
        :20
    ]
    cache = data_dir / "cover-previews"
    target = cache / f"{asset_id}-{version}.jpg"
    with _locks[asset_id % len(_locks)]:
        if target.is_file():
            return target
        cache.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            image.draft("RGB", (768, 512))
            image = ImageOps.exif_transpose(image)
            image.thumbnail((768, 512), Image.Resampling.LANCZOS, reducing_gap=3)
            with tempfile.NamedTemporaryFile(dir=cache, suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                try:
                    image.convert("RGB").save(output, format="JPEG", quality=85)
                except Exception:
                    output.close()
                    temporary.unlink(missing_ok=True)
                    raise
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        for stale in cache.glob(f"{asset_id}-*.jpg"):
            if stale != target:
                try:
                    stale.unlink()
                except OSError:
                    pass  # Another response may still be sending this version on Windows.
    return target
