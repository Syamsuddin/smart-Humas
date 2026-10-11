"""Klien WP REST API (stdlib saja) memakai application password akun editor-ai."""

from __future__ import annotations

import base64
import json
import mimetypes
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..errors import NotConfigured, WPRejected


@dataclass
class Response:
    status: int
    data: Any
    headers: dict[str, str]

    @property
    def total(self) -> int | None:
        v = self.headers.get("x-wp-total")
        return int(v) if v and v.isdigit() else None

    @property
    def total_pages(self) -> int | None:
        v = self.headers.get("x-wp-totalpages")
        return int(v) if v and v.isdigit() else None


class WPRest:
    def __init__(self, base_url: str, user: str | None, app_password: str | None, *, rest_prefix: str = "/wp-json",
                 host_header: str | None = None, verify_tls: bool = True, timeout: float = 30.0,
                 bridge_key: str | None = None):
        if not base_url:
            raise NotConfigured("site.url / site.rest_base belum diatur di config.yaml.")
        self.base = base_url.rstrip("/")
        self.prefix = rest_prefix
        self.host_header = host_header or None
        self.timeout = timeout
        self.bridge_key = bridge_key or None
        self._auth = None
        if user and app_password:
            token = base64.b64encode(f"{user}:{app_password.replace(' ', '')}".encode()).decode()
            self._auth = f"Basic {token}"
        self._ctx = None if verify_tls else ssl._create_unverified_context()  # noqa: SLF001 - hanya bila diminta config

    def url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = f"{self.base}{self.prefix}{path}"
        if params:
            clean = {}
            for k, v in params.items():
                if v is None:
                    continue
                if isinstance(v, (list, tuple)):
                    v = ",".join(str(x) for x in v)
                elif isinstance(v, bool):
                    v = "true" if v else "false"
                clean[k] = v
            if clean:
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(clean)
        return url

    def request(self, method: str, path: str, *, params: dict | None = None, json_body: Any = None,
                data: bytes | None = None, headers: dict[str, str] | None = None) -> Response:
        hdrs = {"Accept": "application/json", "User-Agent": "wp-mcp/1.0"}
        if self._auth:
            hdrs["Authorization"] = self._auth
        if self.host_header:
            hdrs["Host"] = self.host_header
        if self.bridge_key:
            hdrs["X-WPMCP-Key"] = self.bridge_key
        body = data
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            hdrs["Content-Type"] = "application/json; charset=utf-8"
        hdrs.update(headers or {})
        req = urllib.request.Request(self.url(path, params), data=body, method=method.upper(), headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                raw = resp.read()
                return Response(resp.status, _decode(raw), {k.lower(): v for k, v in resp.headers.items()})
        except urllib.error.HTTPError as exc:
            payload = _decode(exc.read())
            code = payload.get("code") if isinstance(payload, dict) else None
            msg = payload.get("message") if isinstance(payload, dict) else str(payload)[:300]
            raise WPRejected(f"WordPress menolak {method} {path}: {msg}",
                             detail={"http_status": exc.code, "wp_code": code}) from None
        except urllib.error.URLError as exc:
            raise WPRejected(f"WordPress tidak terjangkau di {self.base}: {exc.reason}",
                             detail={"http_status": None}) from None

    # pintasan
    def get(self, path: str, **params: Any) -> Response:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: dict | None = None, **params: Any) -> Response:
        return self.request("POST", path, params=params or None, json_body=body or {})

    def delete(self, path: str, **params: Any) -> Response:
        return self.request("DELETE", path, params=params)

    def upload(self, content: bytes, filename: str, mime: str | None = None) -> Response:
        mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        # nama berkas sudah di-slug ASCII (images.media_filename); bentuk paling kompatibel dengan WordPress
        safe = "".join(ch for ch in filename if ch.isalnum() or ch in "-_.") or "media.bin"
        return self.request("POST", "/wp/v2/media", data=content, headers={
            "Content-Type": mime, "Content-Disposition": f'attachment; filename="{safe}"'})


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw.decode("utf-8", "replace")
