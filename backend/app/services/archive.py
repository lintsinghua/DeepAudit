"""Bounded ZIP ingestion shared by uploads, repository downloads and workers."""

import asyncio
import os
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

from app.core.config import settings


class ArchiveError(ValueError):
    pass


def validate_zip(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > settings.ZIP_MAX_ENTRIES:
        raise ArchiveError("ZIP contains too many entries")
    total = 0
    names = set()
    for entry in entries:
        name = entry.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or ":" in name
            or "\x00" in name
            or not path.parts
        ):
            raise ArchiveError("ZIP contains an unsafe path")
        mode = entry.external_attr >> 16
        if stat.S_ISLNK(mode) or (
            stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))
        ):
            raise ArchiveError("ZIP links and special files are not allowed")
        canonical = str(path).casefold()
        if canonical in names:
            raise ArchiveError("ZIP contains duplicate paths")
        names.add(canonical)
        if entry.flag_bits & 1:
            raise ArchiveError("Encrypted ZIP files are not supported")
        if entry.file_size > settings.ZIP_MAX_FILE_BYTES:
            raise ArchiveError("ZIP entry exceeds the per-file quota")
        total += entry.file_size
        if total > settings.ZIP_MAX_EXTRACTED_BYTES:
            raise ArchiveError("ZIP exceeds the total extraction quota")
        if entry.file_size > max(entry.compress_size, 1) * settings.ZIP_MAX_COMPRESSION_RATIO:
            raise ArchiveError("ZIP compression ratio exceeds the quota")
    return entries


def extract_zip(
    archive: zipfile.ZipFile,
    destination: str,
    *,
    strip_root: bool = False,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    entries = validate_zip(archive)
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ArchiveError("ZIP destination must be empty")
    useful = [e for e in entries if not e.filename.startswith("__MACOSX/")]
    parts = [PurePosixPath(e.filename.replace("\\", "/")).parts for e in useful]
    prefix = None
    if strip_root and parts and len({p[0] for p in parts}) == 1:
        first = parts[0][0]
        if all(len(p) > 1 or e.is_dir() for p, e in zip(parts, useful)):
            prefix = first
    # Stage writes so a corrupt archive, quota violation or cancellation leaves no partial tree.
    with tempfile.TemporaryDirectory(prefix=".extract-", dir=root.parent) as staging:
        stage = Path(staging)
        total = 0
        for entry in useful:
            if cancel_check and cancel_check():
                raise asyncio.CancelledError("ZIP extraction cancelled")
            path = PurePosixPath(entry.filename.replace("\\", "/"))
            if prefix:
                path = PurePosixPath(*path.parts[1:])
            if str(path) == ".":
                continue
            target = stage.joinpath(*path.parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(entry) as source, target.open("xb") as output:
                while chunk := source.read(64 * 1024):
                    if cancel_check and cancel_check():
                        raise asyncio.CancelledError("ZIP extraction cancelled")
                    written += len(chunk)
                    total += len(chunk)
                    if (
                        written > settings.ZIP_MAX_FILE_BYTES
                        or total > settings.ZIP_MAX_EXTRACTED_BYTES
                    ):
                        raise ArchiveError("ZIP extraction quota exceeded")
                    output.write(chunk)
        for child in stage.iterdir():
            os.replace(child, root / child.name)


async def save_upload(upload, destination: str) -> None:
    """Apply the quota while reading, before the whole request reaches disk."""
    import aiofiles

    try:
        total = 0
        async with aiofiles.open(destination, "wb") as output:
            while chunk := await upload.read(64 * 1024):
                total += len(chunk)
                if total > settings.ZIP_MAX_UPLOAD_BYTES:
                    raise ArchiveError("ZIP upload exceeds the quota")
                await output.write(chunk)

        def validate():
            with zipfile.ZipFile(destination) as archive:
                validate_zip(archive)

        await asyncio.to_thread(validate)
    except (ArchiveError, zipfile.BadZipFile) as exc:
        Path(destination).unlink(missing_ok=True)
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BaseException:
        Path(destination).unlink(missing_ok=True)
        raise
