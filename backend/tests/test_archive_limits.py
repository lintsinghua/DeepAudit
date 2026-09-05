import asyncio
import io
import stat
import zipfile
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from app.services import archive


def make_zip(entries, compression=zipfile.ZIP_STORED):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as output:
        for name, content in entries:
            output.writestr(name, content)
    buffer.seek(0)
    return buffer


@pytest.mark.parametrize(
    "name", ["../escape.py", "/escape.py", "a/../../escape.py", "a\\..\\escape.py", "C:/escape.py"]
)
def test_rejects_unsafe_paths_before_writing(tmp_path, name):
    with zipfile.ZipFile(make_zip([("good.py", "ok"), (name, "bad")])) as source:
        with pytest.raises(archive.ArchiveError):
            archive.extract_zip(source, str(tmp_path / "out"))
    assert not list(tmp_path.rglob("*.py"))


def test_rejects_links_and_case_collisions():
    link = zipfile.ZipInfo("link")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    for entries in [[(link, "../../outside")], [("A.py", "a"), ("a.py", "b")]]:
        with zipfile.ZipFile(make_zip(entries)) as source:
            with pytest.raises(archive.ArchiveError):
                archive.validate_zip(source)


@pytest.mark.parametrize(
    "setting,value,entries",
    [
        ("ZIP_MAX_ENTRIES", 1, [("a", "a"), ("b", "b")]),
        ("ZIP_MAX_FILE_BYTES", 2, [("a", "abc")]),
        ("ZIP_MAX_EXTRACTED_BYTES", 3, [("a", "ab"), ("b", "cd")]),
        ("ZIP_MAX_COMPRESSION_RATIO", 2, [("a", "a" * 10000)]),
    ],
)
def test_each_resource_quota(monkeypatch, setting, value, entries):
    monkeypatch.setattr(archive.settings, setting, value)
    with zipfile.ZipFile(make_zip(entries, zipfile.ZIP_DEFLATED)) as source:
        with pytest.raises(archive.ArchiveError):
            archive.validate_zip(source)


@pytest.mark.parametrize(
    "entries,expected",
    [
        ([("root/a.py", "a"), ("root/b.py", "b")], ["a.py", "b.py"]),
        ([("README.md", "readme"), ("src/a.py", "a")], ["README.md", "src/a.py"]),
    ],
)
def test_strip_common_directory_preserves_root_files(tmp_path, entries, expected):
    with zipfile.ZipFile(make_zip(entries)) as source:
        archive.extract_zip(source, str(tmp_path), strip_root=True)
    assert (
        sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()) == expected
    )


def test_cancellation_discards_staged_files(tmp_path):
    checks = iter([False, False, True])
    with zipfile.ZipFile(make_zip([("first", "ok"), ("second", "no")])) as source:
        with pytest.raises(asyncio.CancelledError):
            archive.extract_zip(source, str(tmp_path / "out"), cancel_check=lambda: next(checks))
    assert list((tmp_path / "out").iterdir()) == []
    assert list(tmp_path.iterdir()) == [tmp_path / "out"]


async def test_upload_stops_at_quota_and_removes_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(archive.settings, "ZIP_MAX_UPLOAD_BYTES", 3)
    upload = AsyncMock()
    upload.read.side_effect = [b"abc", b"d", b"should not read"]
    destination = tmp_path / "upload.zip"
    with pytest.raises(HTTPException) as error:
        await archive.save_upload(upload, str(destination))
    assert error.value.status_code == 400
    assert upload.read.await_count == 2
    assert not destination.exists()


@pytest.mark.parametrize("declare_size", [True, False])
async def test_multipart_limit_runs_before_spooling_full_request(monkeypatch, declare_size):
    import httpx
    from fastapi import FastAPI, File, UploadFile
    from app.core.upload_limit import UploadLimitMiddleware, settings as upload_settings

    monkeypatch.setattr(upload_settings, "ZIP_MAX_UPLOAD_BYTES", 8)
    monkeypatch.setattr(archive.settings, "ZIP_MAX_UPLOAD_BYTES", 8)
    app = FastAPI()
    app.add_middleware(UploadLimitMiddleware)
    called = []

    @app.post("/api/v1/scan/upload-zip")
    async def upload(file: UploadFile = File(...)):
        called.append(True)
        return {}

    consumed = []

    async def body():
        yield b'--test\r\nContent-Disposition: form-data; name="file"; filename="a.zip"\r\nContent-Type: application/zip\r\n\r\n'
        for index in range(10):
            consumed.append(index)
            yield b"x" * (512 * 1024)
        yield b"\r\n--test--\r\n"

    headers = {"Content-Type": "multipart/form-data; boundary=test"}
    if declare_size:
        headers["Content-Length"] = str(6 * 1024 * 1024)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/scan/upload-zip", content=body(), headers=headers)
    assert response.status_code == 413
    assert not called
    assert len(consumed) < 10
