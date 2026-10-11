"""Uji ujung ke ujung lewat protokol MCP stdio yang sesungguhnya (seperti Claude Code lewat SSH)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


def _run(env_obj, actor: str, calls: list[tuple[str, dict]]):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "wp_mcp", "--config-dir", str(env_obj.cfgdir), "serve", "--actor", actor],
        env={"PYTHONPATH": str(ROOT), "FAKE_WP_LOG": str(env_obj.cli_log)}, cwd=str(ROOT))

    async def main():
        async with Client(params, read_timeout_seconds=60) as client:
            tools = await client.list_tools()
            results = []
            for name, args in calls:
                res = await client.call_tool(name, args)
                results.append(json.loads(res.content[0].text))
            return tools, results

    return asyncio.run(main())


def test_stdio_lists_tools_and_enforces_roles(env_dir):
    tools, results = _run(env_dir, "admin1", [
        ("get_editorial_context", {"purpose": "berita"}),
        ("create_draft", {"title": "Uji MCP", "content_markdown": "KOTA BARU - Kepala BKD, Budi Santosa, hadir."}),
        ("leader_edit", {"post_id": 1, "instruction": "x"}),
    ])
    names = {t.name for t in tools.tools}
    assert {"create_draft", "approve_and_publish", "confirm_action", "verify_names"} <= names
    schema = next(t for t in tools.tools if t.name == "approve_and_publish").input_schema
    assert "_delegation_id" not in json.dumps(schema)  # parameter internal tidak terlihat klien
    assert next(t for t in tools.tools if t.name == "approve_and_publish").annotations.destructive_hint is True

    ctxr, draft, leader = results
    assert ctxr["ok"] and ctxr["data"]["local"]["opd_singkatan"] == "BKPSDM"
    assert ctxr["data"]["role"] == "admin-web"
    assert draft["ok"] and "Budi Santoso" in env_dir.wp.posts[draft["data"]["id"]]["content"]
    assert leader["error"]["code"] == "NOT_AUTHORIZED"  # admin-web bukan pimpinan


def test_stdio_rejects_unknown_actor(env_dir):
    try:
        _run(env_dir, "penyusup", [])
    except Exception:
        return
    raise AssertionError("server dengan aktor tak terdaftar seharusnya gagal start")
