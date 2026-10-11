"""WordPress palsu: server HTTP yang meniru endpoint WP REST yang dipakai WP-MCP.

Cukup setia untuk menguji klien REST, kebijakan, dan alur kerja lewat HTTP sungguhan:
posts/pages (context=edit, meta, status), kategori, tag, media (unggah biner), komentar, users/me, ping bridge.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse


class FakeWP:
    def __init__(self):
        self.lock = threading.Lock()
        self.next_id = 100
        self.posts: dict[int, dict] = {}
        self.terms = {"categories": {}, "tags": {}}
        self.media: dict[int, dict] = {}
        self.media_bytes: dict[int, bytes] = {}
        self.comments: dict[int, dict] = {}
        self.me = {"id": 7, "slug": "editor-ai", "name": "Editor AI", "roles": ["editor_ai"],
                   "capabilities": {"publish_posts": True, "edit_posts": True}}
        self.requests: list[tuple[str, str]] = []
        self.pending: dict[str, dict] = {}   # halaman Persetujuan WP-MCP (plugin bridge)
        self.base = ""
        for name in ("Berita", "Pengumuman", "Kegiatan Pimpinan"):
            self._term("categories", name)

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def _term(self, kind: str, name: str) -> dict:
        tid = self._id()
        t = {"id": tid, "name": name, "slug": name.lower().replace(" ", "-"), "count": 0, "parent": 0}
        self.terms[kind][tid] = t
        return t

    # --- representasi -----------------------------------------------------
    def post_view(self, p: dict) -> dict:
        v = dict(p)
        v["title"] = {"raw": p["title"], "rendered": p["title"]}
        v["content"] = {"raw": p["content"], "rendered": p["content"]}
        v["excerpt"] = {"raw": p.get("excerpt", ""), "rendered": p.get("excerpt", "")}
        v["link"] = f"{self.base}/?p={p['id']}"
        return v

    def comment_view(self, c: dict) -> dict:
        v = dict(c)
        v["content"] = {"raw": c["content"], "rendered": f"<p>{c['content']}</p>"}
        return v


class Handler(BaseHTTPRequestHandler):
    wp: FakeWP = None  # type: ignore[assignment]

    def log_message(self, *a):  # senyap
        pass

    def _send(self, status: int, data, headers: dict | None = None):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, str(v))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, status: int, code: str, msg: str):
        self._send(status, {"code": code, "message": msg, "data": {"status": status}})

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _route(self, method: str):
        wp = self.wp
        u = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(u.query).items()}
        path = u.path
        wp.requests.append((method, self.path))
        if not path.startswith("/wp-json"):
            return self._err(404, "rest_no_route", "no route")
        path = path[len("/wp-json"):]
        if not self.headers.get("Authorization"):
            return self._err(401, "rest_not_logged_in", "Anda belum login.")
        with wp.lock:
            if path == "/wpmcp/v1/ping":
                return self._send(200, {"plugin": "wp-mcp-bridge", "version": "1.0.0", "role_ok": True})
            if path == "/wpmcp/v1/pending" and method == "POST":
                data = json.loads(self._body() or b"{}")
                wp.pending[data["id"]] = {**data, "decision": "pending"}
                return self._send(200, {"stored": data["id"]})
            m = re.fullmatch(r"/wpmcp/v1/approvals/(act_[a-f0-9]+)", path)
            if m:
                a = wp.pending.get(m.group(1))
                if not a:
                    return self._err(404, "wpmcp_not_found", "aksi tidak ada")
                return self._send(200, {"id": a["id"], "decision": a["decision"], "user_login": a.get("decided_by")})
            if path == "/wp/v2/users/me":
                return self._send(200, wp.me)
            m = re.fullmatch(r"/wp/v2/(posts|pages)(?:/(\d+))?", path)
            if m:
                return self._posts(method, m.group(1), int(m.group(2)) if m.group(2) else None, q)
            m = re.fullmatch(r"/wp/v2/(categories|tags)(?:/(\d+))?", path)
            if m:
                return self._terms(method, m.group(1), int(m.group(2)) if m.group(2) else None, q)
            m = re.fullmatch(r"/wp/v2/media(?:/(\d+))?", path)
            if m:
                return self._media(method, int(m.group(1)) if m.group(1) else None, q)
            m = re.fullmatch(r"/wp/v2/comments(?:/(\d+))?", path)
            if m:
                return self._comments(method, int(m.group(1)) if m.group(1) else None, q)
        return self._err(404, "rest_no_route", f"no route {path}")

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_DELETE(self):
        self._route("DELETE")

    # --- posts ------------------------------------------------------------
    def _posts(self, method, kind, pid, q):
        wp = self.wp
        ptype = "post" if kind == "posts" else "page"
        if pid is None and method == "GET":
            statuses = (q.get("status") or "publish").split(",")
            items = [p for p in wp.posts.values() if p["type"] == ptype and p["status"] in statuses]
            if q.get("search"):
                items = [p for p in items if q["search"].lower() in p["title"].lower()]
            items.sort(key=lambda p: p["modified"], reverse=True)
            per, page = int(q.get("per_page", 10)), int(q.get("page", 1))
            chunk = items[(page - 1) * per: page * per]
            pages = max(1, -(-len(items) // per))
            return self._send(200, [wp.post_view(p) for p in chunk], {"X-WP-Total": len(items), "X-WP-TotalPages": pages})
        if pid is None and method == "POST":
            data = json.loads(self._body() or b"{}")
            p = {"id": wp._id(), "type": ptype, "title": data.get("title", ""), "content": data.get("content", ""),
                 "excerpt": data.get("excerpt", ""), "status": data.get("status", "draft"), "categories": data.get("categories", []),
                 "tags": data.get("tags", []), "featured_media": data.get("featured_media", 0), "meta": data.get("meta", {}),
                 "date": "2026-10-11T09:00:00", "modified": len(wp.posts) + 1, "author": wp.me["id"]}
            wp.posts[p["id"]] = p
            return self._send(201, wp.post_view(p))
        p = wp.posts.get(pid)
        if not p or p["type"] != ptype:
            return self._err(404, "rest_post_invalid_id", "ID post tidak valid.")
        if method == "GET":
            return self._send(200, wp.post_view(p))
        if method == "DELETE":
            p["status"] = "trash"
            return self._send(200, wp.post_view(p))
        data = json.loads(self._body() or b"{}")
        for k in ("title", "content", "excerpt", "status", "categories", "tags", "featured_media", "date"):
            if k in data:
                p[k] = data[k]
        p["meta"] = {**p.get("meta", {}), **(data.get("meta") or {})}
        p["modified"] = max(x["modified"] for x in wp.posts.values()) + 1
        return self._send(200, wp.post_view(p))

    # --- terms ------------------------------------------------------------
    def _terms(self, method, kind, tid, q):
        wp = self.wp
        if tid is not None:
            t = wp.terms[kind].get(tid)
            return self._send(200, t) if t else self._err(404, "rest_term_invalid", "term")
        if method == "GET":
            items = list(wp.terms[kind].values())
            if q.get("search"):
                items = [t for t in items if q["search"].lower() in t["name"].lower()]
            return self._send(200, items)
        data = json.loads(self._body() or b"{}")
        return self._send(201, wp._term(kind, data["name"]))

    # --- media ------------------------------------------------------------
    def _media(self, method, mid, q):
        wp = self.wp
        if mid is None and method == "POST":
            raw = self._body()
            disp = self.headers.get("Content-Disposition", "")
            mfn = re.search(r'filename="([^"]+)"', disp)
            fname = unquote(mfn.group(1)) if mfn else "x"
            m = {"id": wp._id(), "source_url": f"{wp.base}/wp-content/uploads/2026/10/{fname}", "alt_text": "",
                 "title": {"raw": fname}, "caption": {"raw": ""}, "post": None, "mime_type": self.headers.get("Content-Type"),
                 "date": "2026-10-11T09:00:00", "media_details": {"sizes": {}}}
            wp.media[m["id"]] = m
            wp.media_bytes[m["id"]] = raw
            return self._send(201, m)
        if mid is None:
            items = list(wp.media.values())
            return self._send(200, items, {"X-WP-Total": len(items), "X-WP-TotalPages": 1})
        m = wp.media.get(mid)
        if not m:
            return self._err(404, "rest_post_invalid_id", "media")
        if method == "POST":
            data = json.loads(self._body() or b"{}")
            for k in ("alt_text", "post"):
                if k in data:
                    m[k] = data[k]
            if "caption" in data:
                m["caption"] = {"raw": data["caption"]}
            if "title" in data:
                m["title"] = {"raw": data["title"]}
        return self._send(200, m)

    # --- comments ---------------------------------------------------------
    def _comments(self, method, cid, q):
        wp = self.wp
        if cid is None and method == "GET":
            items = list(wp.comments.values())
            st = q.get("status")
            if st:
                items = [c for c in items if c["status"] == {"approve": "approved"}.get(st, st)]
            if q.get("author"):
                items = [c for c in items if c["author"] == int(q["author"])]
            if q.get("post"):
                items = [c for c in items if c["post"] == int(q["post"])]
            return self._send(200, [wp.comment_view(c) for c in items])
        if cid is None and method == "POST":
            data = json.loads(self._body() or b"{}")
            c = {"id": wp._id(), "post": data["post"], "parent": data.get("parent", 0), "content": data["content"],
                 "status": data.get("status", "hold"), "author": wp.me["id"], "author_name": data.get("author_name"),
                 "author_email": "", "date": "2026-10-11T09:00:00", "meta": data.get("meta", {})}
            wp.comments[c["id"]] = c
            return self._send(201, wp.comment_view(c))
        c = wp.comments.get(cid)
        if not c:
            return self._err(404, "rest_comment_invalid_id", "comment")
        if method == "POST":
            data = json.loads(self._body() or b"{}")
            if "status" in data:
                c["status"] = {"approve": "approved"}.get(data["status"], data["status"])
        return self._send(200, wp.comment_view(c))


def start_fake_wp() -> tuple[FakeWP, ThreadingHTTPServer, str]:
    wp = FakeWP()
    handler = type("BoundHandler", (Handler,), {"wp": wp})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    wp.base = url
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return wp, srv, url


def decide(wp: FakeWP, action_id: str, login: str, decision: str = "approved") -> None:
    """Meniru manusia yang menekan Setujui/Tolak di wp-admin → Persetujuan WP-MCP."""
    wp.pending[action_id]["decision"] = decision
    wp.pending[action_id]["decided_by"] = login


def add_citizen_comment(wp: FakeWP, post_id: int, content: str, email: str = "warga@gmail.com") -> int:
    cid = wp._id()
    wp.comments[cid] = {"id": cid, "post": post_id, "parent": 0, "content": content, "status": "hold", "author": 0,
                        "author_name": "Warga", "author_email": email, "date": "2026-10-11T08:00:00", "meta": {}}
    return cid
