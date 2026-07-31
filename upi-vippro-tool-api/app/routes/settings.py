from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import ConfigError
from app.logging_setup import update_secrets

router = APIRouter(tags=["settings"])


class ValueBody(BaseModel):
    value: Any


class ModeBody(BaseModel):
    mode: str


@router.get("/api/settings")
async def get_settings(request: Request):
    return request.app.state.config.masked_dict()


@router.put("/api/settings/{key}")
async def put_setting(key: str, body: ValueBody, request: Request):
    cfg = request.app.state.config
    try:
        result = cfg.update_field(key, body.value)
    except ConfigError as e:
        return JSONResponse({"error_code": "validation_error", "message": str(e)}, status_code=400)
    c = cfg.get()
    update_secrets([c.rust_bot_token, c.telegram_bot_token])
    request.app.state.rust_bot.configure(c.rust_bot_base_url, c.rust_bot_token)
    return result


@router.post("/api/settings/bulk")
async def bulk_settings(body: dict[str, Any], request: Request):
    cfg = request.app.state.config
    try:
        result = cfg.update_bulk(body)
    except ConfigError as e:
        return JSONResponse({"error_code": "validation_error", "message": str(e)}, status_code=400)
    c = cfg.get()
    update_secrets([c.rust_bot_token, c.telegram_bot_token])
    request.app.state.rust_bot.configure(c.rust_bot_base_url, c.rust_bot_token)
    return result


@router.post("/api/settings/telegram/mode")
async def telegram_mode(body: ModeBody, request: Request):
    cfg = request.app.state.config
    try:
        result = cfg.update_field("telegram_mode", body.mode)
    except ConfigError as e:
        return JSONResponse({"error_code": "validation_error", "message": str(e)}, status_code=400)
    return {
        "telegram_mode": body.mode,
        "applied_at": result["applied_at"],
    }


@router.post("/api/test/telegram")
async def test_telegram(request: Request):
    """Body optional: {bot_token?, chat_id?} — dùng draft từ Settings UI."""
    body: dict[str, Any] = {}
    try:
        raw = await request.json()
        if isinstance(raw, dict):
            body = raw
    except Exception:
        body = {}
    token = str(body.get("bot_token") or "").strip() or None
    chat = str(body.get("chat_id") or "").strip() or None
    return await request.app.state.telegram.test_send(
        bot_token=token, chat_id=chat
    )


@router.post("/api/test/rust-bot")
async def test_rust_bot(request: Request):
    """Test UPI API. Body optional: {base_url?, token?} — dùng draft từ Settings UI."""
    c = request.app.state.config.get()
    body: dict[str, Any] = {}
    try:
        raw = await request.json()
        if isinstance(raw, dict):
            body = raw
    except Exception:
        body = {}
    base = str(body.get("base_url") or c.rust_bot_base_url or "").strip()
    token = str(body.get("token") or "").strip()
    if not token or "***" in token:
        token = c.rust_bot_token
    if not token:
        return JSONResponse(
            {"ok": False, "status": 0, "error": "token_empty", "latency_ms": 0},
            status_code=400,
        )
    # Client tạm — không mutate global nếu chỉ đang test draft
    from app.rust_bot_client import RustBotClient

    client = RustBotClient(base, token)
    result = await client.me(timeout=10.0)
    # Nếu test OK với draft token khớp form đã save → sync client chính
    if result.get("ok") and token == c.rust_bot_token and base == c.rust_bot_base_url:
        request.app.state.rust_bot.configure(base, token)
    return result


@router.get("/api/account")
async def account_info(request: Request):
    c = request.app.state.config.get()
    request.app.state.rust_bot.configure(c.rust_bot_base_url, c.rust_bot_token)
    return await request.app.state.rust_bot.me(timeout=10.0)
