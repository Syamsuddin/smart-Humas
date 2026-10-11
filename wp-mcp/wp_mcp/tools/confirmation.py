"""Tool konfirmasi aksi tertunda. Dipakai Claude Code (lewat prompt izin) dan gateway (lewat tombol)."""

from __future__ import annotations

from ..policy import HUMAN_ROLES, ToolContext, tool


@tool("list_pending_actions", level="0", group="confirmation")
def list_pending_actions(ctx: ToolContext, mine_only: bool = False) -> dict:
    """Aksi level 2b/3 yang menunggu konfirmasi manusia, dengan ringkasan dampak dan sisa waktu."""
    return {"items": ctx.services.dispatcher.list_pending(ctx.actor.id if mine_only else None)}


@tool("confirm_action", level="1", roles=HUMAN_ROLES, group="confirmation")
def confirm_action(ctx: ToolContext, action_id: str, otp: str | None = None) -> dict:
    """Konfirmasi aksi tertunda (hanya manusia yang berwenang atas aksi itu). Level 3 butuh kode OTP dari Telegram.
    Ditolak bila kedaluwarsa atau konten berubah sejak aksi dibuat. Bacakan ringkasan ke pengguna sebelum memanggil ini."""
    return ctx.services.dispatcher.confirm(ctx.actor.id, action_id, otp, door=ctx.door)  # dipanggil langsung oleh Dispatcher


@tool("cancel_action", level="1", roles=HUMAN_ROLES, group="confirmation")
def cancel_action(ctx: ToolContext, action_id: str) -> dict:
    """Batalkan aksi tertunda (pembuatnya atau pimpinan)."""
    return ctx.services.dispatcher.cancel(ctx.actor.id, action_id)
