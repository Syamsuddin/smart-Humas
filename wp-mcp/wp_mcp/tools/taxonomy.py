"""Tool kategori dan tag."""

from __future__ import annotations

from typing import Literal

from ..errors import NotAuthorized
from ..policy import ToolContext, tool

Tax = Literal["category", "post_tag"]
PATH = {"category": "/wp/v2/categories", "post_tag": "/wp/v2/tags"}


@tool("list_terms", level="0", group="taxonomy")
def list_terms(ctx: ToolContext, taxonomy: Tax = "category", search: str | None = None, limit: int = 100) -> dict:
    """Daftar kategori atau tag yang ada di WordPress."""
    data = ctx.wp.get(PATH[taxonomy], search=search, per_page=max(1, min(int(limit), 100)), orderby="count", order="desc").data
    return {"items": [{"id": t["id"], "name": t["name"], "slug": t.get("slug"), "count": t.get("count"),
                       "parent": t.get("parent")} for t in data or []]}


def _authorize_term(ctx: ToolContext, args: dict) -> None:
    if args.get("taxonomy", "post_tag") == "category" and ctx.actor.role == "operator-ai":
        raise NotAuthorized("Kategori baru hanya dibuat admin-web/pimpinan; operator-ai memilih dari yang ada.")


@tool("create_term", level="1", authorize=_authorize_term, pii_fields=("name", "description"), group="taxonomy")
def create_term(ctx: ToolContext, name: str, taxonomy: Tax = "post_tag", parent_id: int | None = None,
                description: str | None = None) -> dict:
    """Buat tag (semua peran) atau kategori (hanya admin-web/pimpinan)."""
    body = {"name": name}
    if parent_id and taxonomy == "category":
        body["parent"] = int(parent_id)
    if description:
        body["description"] = description
    t = ctx.wp.post(PATH[taxonomy], body).data
    return {"id": t["id"], "name": t["name"], "taxonomy": taxonomy}
