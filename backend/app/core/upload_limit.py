"""Bound ZIP request bodies before Starlette spools multipart uploads to disk."""

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse
from app.core.config import settings


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        is_upload = path == settings.API_V1_STR + "/scan/upload-zip" or (
            path.startswith(settings.API_V1_STR + "/projects/") and path.endswith("/zip")
        )
        if scope["type"] != "http" or scope.get("method") != "POST" or not is_upload:
            return await self.app(scope, receive, send)
        # Multipart boundaries and small form fields have a separate 1 MiB allowance.
        limit = settings.ZIP_MAX_UPLOAD_BYTES + 1024 * 1024
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0
        rejection = JSONResponse(
            {"detail": "ZIP upload exceeds the request quota"}, status_code=413
        )
        if declared > limit:
            return await rejection(scope, receive, send)
        total, exceeded = 0, False

        async def bounded_receive():
            nonlocal total, exceeded
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    exceeded = True
                    # Starlette closes partially spooled files on this exception.
                    raise MultiPartException("ZIP upload exceeds the request quota")
            return message

        async def bounded_send(message):
            if exceeded and message["type"] == "http.response.start":
                message = {**message, "status": 413}
            await send(message)

        try:
            await self.app(scope, bounded_receive, bounded_send)
        except MultiPartException:
            await rejection(scope, receive, send)
