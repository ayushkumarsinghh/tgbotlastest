import asyncio
import aiohttp
import os
import sys
import logging

import json
import re

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8711939395:AAFqMmnEZaVhJ2kk04aLft2llUP8iDOU8G8")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
PUPUX_API_BASE = "https://ai.pupux.xyz/api/paylinks"

# Discord Channels Config (Set DISCORD_TOKEN in Railway Env Variables)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
DISCORD_INPUT_CHANNEL_ID = os.getenv("DISCORD_INPUT_CHANNEL_ID", "1532592499678384248").strip()
DISCORD_DB_CHANNEL_ID = os.getenv("DISCORD_DB_CHANNEL_ID", "1532594541742395425").strip()
LAST_DISCORD_MSG_ID = None
LAST_TG_CHAT_ID = None

# Default runtime state
ACTIVE_CDK = os.getenv("PUPUX_CDK", "")
TOKEN_LIMIT = int(os.getenv("PUPUX_TOKEN_LIMIT", "10"))
PAYMENT_METHOD = "kakao"  # Hardcoded to Kakao pay
AUTHORIZED_WORKERS = {"sleepu69", "royfumbler"}  # Initial authorized admins (lowercase)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

from curl_cffi.requests import AsyncSession

# Add upi-vippro-tool-api to sys.path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "upi-vippro-tool-api"))
try:
    from app.login_service import login_pure_request, LoginError
except Exception as err:
    logger.warning(f"Could not import login_service: {err}")

async def login_account_credential(cred_str):
    cred_str = cred_str.strip()
    if not cred_str:
        return None, "free", "Empty string"

    parts = re.split(r'[|:]', cred_str)
    if len(parts) < 2:
        return None, "free", "Invalid format. Use email|pass|2fa"

    email = parts[0].strip()
    password = parts[1].strip()
    totp_secret = parts[2].strip() if len(parts) >= 3 and parts[2].strip() else None

    logger.info(f"[Pure-HTTP Auth] Logging in {email}...")
    try:
        async with AsyncSession(impersonate="chrome124", timeout=25) as session:
            session_entry = await login_pure_request(email, password, totp_secret, session, logger)
            if session_entry and session_entry.access_token:
                # Detect subscription plan (Plus vs Free)
                plan = "free"
                try:
                    r = await session.get(
                        "https://chatgpt.com/api/auth/session",
                        headers={"Accept": "application/json", "Referer": "https://chatgpt.com/"}
                    )
                    if r.status_code == 200:
                        data = r.json()
                        p = (data.get("subscription_plan") or (data.get("account") or {}).get("planType") or "").lower()
                        if p in ("chatgptplusplan", "plus") or "plus" in p:
                            plan = "plus"
                        elif "team" in p:
                            plan = "team"
                        elif "pro" in p:
                            plan = "pro"
                except Exception as plan_err:
                    logger.warning(f"Plan detection failed for {email}: {plan_err}")

                logger.info(f"[Pure-HTTP Auth] Access Token generated for {email} (Plan: {plan})!")
                return session_entry.access_token, plan, f"Logged in: `{email}` ({plan.upper()})"
    except Exception as le:
        logger.error(f"[Pure-HTTP Auth] Login error for {email}: {le}")
        return None, "free", f"Login failed for `{email}` ({str(le)})"

    return None, "free", f"Unknown login error for `{email}`"

async def process_and_extract_credentials(text, http=None, chat_id=None):
    if not text:
        return []

    tokens = []
    lines = text.splitlines()

    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        # 1. Check if line is email|pass|2fa or email:pass:2fa format
        if "@" in line_str and ("|" in line_str or ":" in line_str) and not line_str.startswith("eyJ"):
            parts = re.split(r'[|:]', line_str)
            if len(parts) >= 2:
                email = parts[0].strip()
                if chat_id and http:
                    await send_tg_message(http, chat_id, f"**Authenticating Account** (`{email}`)... Please wait...")

                token, plan, status_msg = await login_account_credential(line_str)
                if token:
                    tokens.append(token)
                    if chat_id and http:
                        await send_tg_message(http, chat_id, f"`{email}` ({plan.upper()}): **Logged In & Access Token Generated!**")
                        # If CDK key is set, automatically trigger Pupux Kakao Pay QR Code generation!
                        if ACTIVE_CDK:
                            asyncio.create_task(execute_extraction_batch(http, chat_id, [token]))
                else:
                    if chat_id and http:
                        await send_tg_message(http, chat_id, status_msg)
                continue

        # 2. Extract raw JWT tokens starting with eyJ
        jwt_matches = re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', line_str)
        for jm in jwt_matches:
            if len(jm) > 50 and jm not in tokens:
                tokens.append(jm)

        # 3. Direct tokens without eyJ prefix
        if len(line_str) > 50 and line_str not in tokens and not line_str.startswith("eyJ"):
            if not ("@" in line_str and ("|" in line_str or ":" in line_str)):
                tokens.append(line_str)

    return tokens

def extract_access_tokens_from_text(text):
    tokens = []
    if not text:
        return tokens
        
    lines = text.splitlines()
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        # 1. Try parsing JSON directly to find "accessToken"
        try:
            data = json.loads(line_str)
            if isinstance(data, dict):
                acc_tok = data.get("accessToken")
                if acc_tok and isinstance(acc_tok, str) and len(acc_tok) > 50:
                    if acc_tok.strip() not in tokens:
                        tokens.append(acc_tok.strip())
                    continue
        except Exception:
            pass
            
        # 2. Search regex for "accessToken": "..." in line
        match = re.search(r'"accessToken"\s*:\s*"([^"]+)"', line_str)
        if match:
            tok = match.group(1).strip()
            if len(tok) > 50 and tok not in tokens:
                tokens.append(tok)
                continue
                
        # 3. Search regex for raw JWT tokens starting with eyJ
        jwt_matches = re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', line_str)
        for jm in jwt_matches:
            if len(jm) > 50 and jm not in tokens:
                tokens.append(jm)

    return tokens

def load_stock():
    if not os.path.exists(STOCK_FILE):
        return []
    with open(STOCK_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def save_stock(tokens):
    with open(STOCK_FILE, "w", encoding="utf-8") as f:
        for t in tokens:
            f.write(f"{t}\n")

def get_discord_headers():
    tok = DISCORD_TOKEN.strip()
    if not tok:
        return {}
    if not tok.startswith("Bot "):
        tok = f"Bot {tok}"
    return {"Authorization": tok}

async def push_stock_to_discord_db(http):
    headers = get_discord_headers()
    if not headers or not DISCORD_DB_CHANNEL_ID:
        return
    url = f"https://discord.com/api/v9/channels/{DISCORD_DB_CHANNEL_ID}/messages"
    tokens = load_stock()
    
    content_payload = f"**Token Stock DB Backup** — `{len(tokens)}` unused token(s) in pool."
    
    if not os.path.exists(STOCK_FILE):
        return

    try:
        data = aiohttp.FormData()
        data.add_field("payload_json", json.dumps({"content": content_payload}))
        with open(STOCK_FILE, "rb") as f:
            data.add_field("file", f, filename="token_stock.txt", content_type="text/plain")
            
        async with http.post(url, headers=headers, data=data, timeout=15) as resp:
            if resp.status == 200:
                logger.info(f"[Discord DB] Backed up {len(tokens)} token(s) to Discord DB Channel ({DISCORD_DB_CHANNEL_ID}).")
            else:
                resp_text = await resp.text()
                logger.error(f"[Discord DB] Failed to backup stock: {resp.status} - {resp_text}")
    except Exception as e:
        logger.error(f"[Discord DB] Exception uploading stock to Discord DB: {e}")

async def restore_stock_from_discord_db(http):
    headers = get_discord_headers()
    if not headers or not DISCORD_DB_CHANNEL_ID:
        return
    url = f"https://discord.com/api/v9/channels/{DISCORD_DB_CHANNEL_ID}/messages?limit=10"
    try:
        async with http.get(url, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                msgs = await resp.json()
                if msgs and isinstance(msgs, list):
                    for msg in msgs:
                        attachments = msg.get("attachments", [])
                        for att in attachments:
                            if att.get("filename") == "token_stock.txt" or att.get("url", "").endswith(".txt"):
                                att_url = att.get("url")
                                async with http.get(att_url, timeout=10) as att_resp:
                                    if att_resp.status == 200:
                                        att_text = await att_resp.text()
                                        restored_tokens = extract_access_tokens_from_text(att_text)
                                        if restored_tokens:
                                            save_stock(restored_tokens)
                                            logger.info(f"[Discord DB] Restored {len(restored_tokens)} token(s) from Discord DB Channel!")
                                            return
    except Exception as e:
        logger.error(f"[Discord DB] Error restoring stock from Discord DB: {e}")

def add_to_stock(new_tokens, http=None):
    existing = load_stock()
    existing_set = set(existing)
    added = 0
    for t in new_tokens:
        if t not in existing_set:
            existing.append(t)
            existing_set.add(t)
            added += 1
    save_stock(existing)
    if added > 0 and http:
        asyncio.create_task(push_stock_to_discord_db(http))
    return added, len(existing)

def pop_from_stock(count, http=None):
    existing = load_stock()
    selected = existing[:count]
    remaining = existing[count:]
    save_stock(remaining)
    if http:
        asyncio.create_task(push_stock_to_discord_db(http))
    return selected, len(remaining)

def is_authorized(username):
    if not username:
        return False
    return username.lower().lstrip('@') in AUTHORIZED_WORKERS

async def send_tg_message(http, chat_id, text, reply_markup=None, parse_mode="Markdown"):
    url = f"{TG_API}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with http.post(url, json=payload) as r:
            res = await r.json()
            if not res.get("ok"):
                payload.pop("parse_mode", None)
                await http.post(url, json=payload)
            return res
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return None

async def send_tg_photo(http, chat_id, photo_url, caption="", parse_mode="Markdown"):
    url = f"{TG_API}/sendPhoto"
    payload = {"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": parse_mode}
    try:
        async with http.post(url, json=payload) as r:
            res = await r.json()
            if not res.get("ok"):
                await send_tg_message(http, chat_id, f"{caption}\n\nQR Image: {photo_url}")
            return res
    except Exception:
        await send_tg_message(http, chat_id, f"{caption}\n\nQR Image: {photo_url}")

async def edit_tg_message(http, chat_id, message_id, text, parse_mode="Markdown"):
    url = f"{TG_API}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
    try:
        async with http.post(url, json=payload) as r:
            res = await r.json()
            if not res.get("ok"):
                payload.pop("parse_mode", None)
                await http.post(url, json=payload)
            return res
    except Exception as e:
        logger.error(f"Failed to edit message: {e}")

async def execute_extraction_batch(http, chat_id, tokens):
    global ACTIVE_CDK, TOKEN_LIMIT

    if not ACTIVE_CDK:
        await send_tg_message(http, chat_id, "**CDK Key is not configured yet!**\nPlease set it using `/setcdk <CDK_KEY>`.")
        return

    init_res = await send_tg_message(
        http, chat_id,
        f"**Processing {len(tokens)} Kakao Pay Access Token(s)...**\n"
        f"CDK: `{ACTIVE_CDK[:6]}...` | Limit: `{TOKEN_LIMIT}`"
    )
    status_msg_id = init_res.get("result", {}).get("message_id") if init_res else None

    # 1. Submit Tasks Batch to Pupux API (Hardcoded Kakao Pay)
    payload = {
        "payment_method": "kakao",
        "cdk": ACTIVE_CDK,
        "access_tokens": tokens
    }
    
    try:
        async with http.post(f"{PUPUX_API_BASE}/tasks/batch", json=payload, timeout=20) as resp:
            res = await resp.json()
            if not res.get("ok"):
                error_detail = res.get("detail", "Unknown error")
                if status_msg_id:
                    await edit_tg_message(http, chat_id, status_msg_id, f"**API Submission Failed**\nReason: `{error_detail}`")
                else:
                    await send_tg_message(http, chat_id, f"**API Submission Failed**\nReason: `{error_detail}`")
                return

            tasks = res.get("tasks", [])
            submitted_count = res.get("submitted", 0)
    except Exception as err:
        if status_msg_id:
            await edit_tg_message(http, chat_id, status_msg_id, f"**Connection Error**: Failed to reach Pupux API (`{err}`)")
        else:
            await send_tg_message(http, chat_id, f"**Connection Error**: Failed to reach Pupux API (`{err}`)")
        return

    if not tasks:
        if status_msg_id:
            await edit_tg_message(http, chat_id, status_msg_id, "No tasks returned from API submission.")
        return

    if status_msg_id:
        await edit_tg_message(http, chat_id, status_msg_id, f"**Submitted {submitted_count} Kakao Pay tasks.** Polling results...")

    # Map task_id -> sequential number (1, 2, 3...)
    task_num_map = {t["task_id"]: i + 1 for i, t in enumerate(tasks)}
    pending_task_ids = set(task_num_map.keys())

    # 2. Poll status until all tasks complete
    results_delivered = 0
    while pending_task_ids:
        await asyncio.sleep(3)
        ids_str = ",".join(list(pending_task_ids)[:50]) # max 50 per status check
        try:
            async with http.get(f"{PUPUX_API_BASE}/tasks/statuses?task_ids={ids_str}", timeout=15) as s_resp:
                s_res = await s_resp.json()
                items = s_res.get("items", [])
                
                for item in items:
                    tid = item.get("task_id")
                    st = item.get("status")
                    
                    if st == "succeeded":
                        num = task_num_map.get(tid, 1)
                        res_obj = item.get("result") or {}
                        pay_url = res_obj.get("payment_url", "N/A")
                        qr_url = res_obj.get("png_url") or res_obj.get("svg_url") or res_obj.get("qr_url")

                        card_text = (
                            f"**Kakao Pay Link #{num}**\n"
                            f"Task ID: `{tid}`\n"
                            f"**Payment Link**:\n`{pay_url}`"
                        )

                        if qr_url:
                            await send_tg_photo(http, chat_id, qr_url, caption=card_text)
                        else:
                            await send_tg_message(http, chat_id, card_text)

                        pending_task_ids.discard(tid)
                        results_delivered += 1

                    elif st in ["failed", "cancelled", "stale"]:
                        num = task_num_map.get(tid, 1)
                        fail_obj = item.get("failure") or {}
                        summary_fail = fail_obj.get("summary") or st
                        await send_tg_message(
                            http, chat_id,
                            f"**Kakao Pay Link #{num} Failed** (Task ID: `{tid}`)\nReason: `{summary_fail}`"
                        )
                        pending_task_ids.discard(tid)
        except Exception as poll_err:
            logger.error(f"Polling error: {poll_err}")

    remaining_stock = len(load_stock())
    final_text = (
        f"**Completed! Delivered {results_delivered}/{submitted_count} Kakao Pay Links.**\n"
        f"Unused Stock Remaining: `{remaining_stock}` tokens."
    )
    if status_msg_id:
        await edit_tg_message(http, chat_id, status_msg_id, final_text)
    else:
        await send_tg_message(http, chat_id, final_text)

async def handle_update(http, update):
    global ACTIVE_CDK, TOKEN_LIMIT, AUTHORIZED_WORKERS, LAST_TG_CHAT_ID

    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat_id = message.get("chat", {}).get("id")
    if chat_id:
        LAST_TG_CHAT_ID = chat_id
    text = message.get("text", "").strip()
    from_user = message.get("from", {})
    username = from_user.get("username", "")

    if not text or not chat_id:
        return

    # Enforce strict user authorization for ALL bot interactions
    if not is_authorized(username):
        await send_tg_message(http, chat_id, "Access Denied: Only authorized users can use this bot. Contact @Sleepu69 for access.")
        return

    # Command Handling
    cmd = text.split()[0].lower() if text else ""

    if cmd == "/start":
        welcome_text = (
            "**Kakao Pay Instant QR Bot**\n\n"
            "**Quick Kakao Pay QR Generation**:\n"
            "• Simply paste `email|password|2fa_secret` or send `/run email|password|2fa_secret`!\n"
            "• Pure-HTTP authenticates in 1-2s and delivers your **Kakao Pay QR Code & Payment Link** directly!\n\n"
            "**Commands**:\n"
            "• `/run <email|pass|2fa>` — Generate Kakao Pay QR & Payment Link directly\n"
            "• `/setcdk <CDK_KEY>` — Set active Pupux CDK License Key\n"
            "• `/status` — View full bot configuration & CDK status\n"
            "• `/adduser <@username>` — Authorize a new user\n"
            "• `/removeuser <@username>` — Revoke a user's access"
        )
        await send_tg_message(http, chat_id, welcome_text)
        return

    if cmd == "/status":
        cdk_display = f"`{ACTIVE_CDK}`" if ACTIVE_CDK else "*Not Set* (Use `/setcdk <KEY>`)"
        workers_str = ", ".join([f"@{w}" for w in AUTHORIZED_WORKERS]) if AUTHORIZED_WORKERS else "None"
        msg = (
            "**Bot Configuration Status**\n\n"
            f"**Payment Method**: `Kakao Pay` (Hardcoded)\n"
            f"**Active CDK Key**: {cdk_display}\n"
            f"**Authorized Users**: {workers_str}\n"
        )
        await send_tg_message(http, chat_id, msg)
        return

    if cmd == "/setcdk":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_tg_message(http, chat_id, "**Usage**: `/setcdk <YOUR_CDK_KEY>`")
            return
        ACTIVE_CDK = parts[1].strip()
        await send_tg_message(http, chat_id, f"**CDK Key Updated Successfully!**\nNew CDK: `{ACTIVE_CDK}`")
        return

    if cmd in ["/addworker", "/adduser"]:
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_tg_message(http, chat_id, "**Usage**: `/adduser <@username>`")
            return
        un = parts[1].strip().lstrip('@').lower()
        AUTHORIZED_WORKERS.add(un)
        await send_tg_message(http, chat_id, f"**Authorized User Added!**\n@{un} can now use the bot.")
        return

    if cmd in ["/removeworker", "/removeuser"]:
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_tg_message(http, chat_id, "**Usage**: `/removeuser <@username>`")
            return
        un = parts[1].strip().lstrip('@').lower()
        AUTHORIZED_WORKERS.discard(un)
        await send_tg_message(http, chat_id, f"**User Authorization Revoked!**\n@{un} can no longer use the bot.")
        return

    if cmd == "/run":
        parts = text.split(maxsplit=1)
        raw_arg = parts[1] if len(parts) > 1 else ""
        
        reply_to = message.get("reply_to_message")
        if not raw_arg and reply_to:
            raw_arg = reply_to.get("text", "")

        if not raw_arg:
            await send_tg_message(http, chat_id, "**Usage**: `/run email|password|2fa_secret`\nOr reply to an `email|password|2fa_secret` message with `/run`!")
            return

        tokens = await process_and_extract_credentials(raw_arg, http=http, chat_id=chat_id)
        if not tokens:
            await send_tg_message(http, chat_id, "**Could not process credentials.** Please format as: `email|password|2fa_secret`")
            return
            
        return

    # Direct credential paste (email|pass|2fa) from anyone automatically processes & generates QR code
    if "@" in text and ("|" in text or ":" in text) and not text.startswith("eyJ"):
        tokens = await process_and_extract_credentials(text, http=http, chat_id=chat_id)
        return
        
    # Direct token paste
    tokens = [line.strip() for line in text.splitlines() if line.strip().startswith("eyJ") or len(line.strip()) > 50]
    if tokens:
        added, total_stock = add_to_stock(tokens, http=http)
        await send_tg_message(
            http, chat_id, 
            f"**{added} Access Token(s) Received & Saved to Stock!**\n"
            f"Total Unused Stock: `{total_stock}` token(s)."
        )

async def maintain_discord_presence(http):
    if not DISCORD_TOKEN:
        return
        
    raw_token = DISCORD_TOKEN.strip()
    clean_token = raw_token[4:].strip() if raw_token.startswith("Bot ") else raw_token

    gateway_url = "wss://gateway.discord.gg/?v=9&encoding=json"
    logger.info("[Discord Presence] Starting Gateway connection to turn Bot Online ...")

    while True:
        try:
            async with http.ws_connect(gateway_url) as ws:
                logger.info("[Discord Presence] Connected to Discord Gateway! Bot is now ONLINE.")
                
                # Identify Payload
                identify_payload = {
                    "op": 2,
                    "d": {
                        "token": clean_token,
                        "intents": 512,
                        "properties": {
                            "$os": "linux",
                            "$browser": "python",
                            "$device": "python"
                        },
                        "presence": {
                            "status": "online",
                            "afk": False,
                            "activities": [{
                                "name": "Session Auto Sync",
                                "type": 0
                            }]
                        }
                    }
                }
                await ws.send_json(identify_payload)

                # Keep heartbeat loop
                while not ws.closed:
                    msg = await ws.receive()
                    if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        op = data.get("op")
                        if op == 10:  # Hello
                            interval_ms = data.get("d", {}).get("heartbeat_interval", 41250)
                            asyncio.create_task(send_gateway_heartbeats(ws, interval_ms / 1000.0))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[Discord Presence] Gateway reconnecting: {e}")
            await asyncio.sleep(5)

async def send_gateway_heartbeats(ws, interval_sec):
    try:
        while not ws.closed:
            await asyncio.sleep(interval_sec)
            if not ws.closed:
                await ws.send_json({"op": 1, "d": None})
    except Exception:
        pass

async def poll_discord_channel(http):
    global LAST_DISCORD_MSG_ID
    headers = get_discord_headers()
    if not headers or not DISCORD_INPUT_CHANNEL_ID:
        logger.info("[Discord Sync] DISCORD_TOKEN or DISCORD_INPUT_CHANNEL_ID not set. Polling disabled.")
        return

    logger.info(f"[Discord Sync] Starting background listener for Discord Input Channel {DISCORD_INPUT_CHANNEL_ID} (2s interval)...")
    url = f"https://discord.com/api/v9/channels/{DISCORD_INPUT_CHANNEL_ID}/messages?limit=10"
    
    # Baseline fetch & extract recent messages
    try:
        async with http.get(url, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                msgs = await resp.json()
                if msgs and isinstance(msgs, list):
                    LAST_DISCORD_MSG_ID = msgs[0].get("id")
                    logger.info(f"[Discord Sync] Baseline Message ID: {LAST_DISCORD_MSG_ID}")
                    
                    # Process initial recent messages
                    msgs.sort(key=lambda m: int(m.get("id", 0)))
                    for msg in msgs:
                        content = msg.get("content", "")
                        author = msg.get("author", {}).get("username", "Unknown")
                        attachments = msg.get("attachments", [])
                        for att in attachments:
                            att_url = att.get("url")
                            filename = att.get("filename", "").lower()
                            if att_url and (filename.endswith(".txt") or filename.endswith(".json") or "text" in att.get("content_type", "")):
                                try:
                                    async with http.get(att_url, timeout=10) as att_resp:
                                        if att_resp.status == 200:
                                            att_text = await att_resp.text()
                                            content += f"\n{att_text}"
                                except Exception as att_err:
                                    logger.error(f"[Discord Sync] Attachment fetch error: {att_err}")

                        extracted = await process_and_extract_credentials(content, http=http)
                        if extracted:
                            added, total_stock = add_to_stock(extracted, http=http)
                            logger.info(f"[Discord Sync] Extracted {added} token(s) from Discord (@{author}). Total stock: {total_stock}")

    except Exception as e:
        logger.error(f"[Discord Sync] Initial fetch error: {e}")

    while True:
        await asyncio.sleep(2)  # Fast 2-second polling interval
        try:
            poll_url = url
            if LAST_DISCORD_MSG_ID:
                poll_url = f"{url}&after={LAST_DISCORD_MSG_ID}"
                
            async with http.get(poll_url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    msgs = await resp.json()
                    if msgs and isinstance(msgs, list):
                        # Sort oldest to newest
                        msgs.sort(key=lambda m: int(m.get("id", 0)))
                        for msg in msgs:
                            msg_id = msg.get("id")
                            content = msg.get("content", "")
                            author = msg.get("author", {}).get("username", "Unknown")
                            
                            # Also check text attachments (.txt, .json, etc.)
                            attachments = msg.get("attachments", [])
                            for att in attachments:
                                att_url = att.get("url")
                                filename = att.get("filename", "").lower()
                                if att_url and (filename.endswith(".txt") or filename.endswith(".json") or "text" in att.get("content_type", "")):
                                    try:
                                        async with http.get(att_url, timeout=10) as att_resp:
                                            if att_resp.status == 200:
                                                att_text = await att_resp.text()
                                                content += f"\n{att_text}"
                                    except Exception as att_err:
                                        logger.error(f"[Discord Sync] Attachment fetch error: {att_err}")

                            extracted = await process_and_extract_credentials(content, http=http)
                            if extracted:
                                added, total_stock = add_to_stock(extracted, http=http)
                                logger.info(f"[Discord Sync] Extracted {added} token(s) from Discord (@{author}). Total stock: {total_stock}")

                            LAST_DISCORD_MSG_ID = msg_id
                elif resp.status == 401:
                    logger.error("[Discord Sync] Invalid Discord Token! HTTP 401 Unauthorized.")
                    await asyncio.sleep(30)
        except asyncio.CancelledError:
            break
        except Exception as err:
            logger.error(f"[Discord Sync] Error polling Discord: {err}")
            await asyncio.sleep(3)

async def main():
    print(f"[System] Starting Kakao Pay Telegram Bot (Direct Telegram API)...")
    offset = 0
    async with aiohttp.ClientSession() as http:
        # Verify bot token
        async with http.get(f"{TG_API}/getMe") as me_resp:
            me_json = await me_resp.json()
            if not me_json.get("ok"):
                print(f"Error: Invalid Telegram BOT_TOKEN: {BOT_TOKEN}")
                return
            bot_info = me_json.get("result", {})
            print(f"Telegram Bot Connected Successfully: @{bot_info.get('username')} ({bot_info.get('first_name')})")

        print("[System] Listening for updates 24/7...")
        while True:
            try:
                url = f"{TG_API}/getUpdates?offset={offset}&timeout=30"
                async with http.get(url, timeout=40) as resp:
                    data = await resp.json()
                    if data.get("ok"):
                        for update in data.get("result", []):
                            offset = update["update_id"] + 1
                            asyncio.create_task(handle_update(http, update))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Poller exception: {e}")
                await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())
