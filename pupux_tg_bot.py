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
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DISCORD_INPUT_CHANNEL_ID = os.getenv("DISCORD_INPUT_CHANNEL_ID", "1532592499678384248")
DISCORD_DB_CHANNEL_ID = os.getenv("DISCORD_DB_CHANNEL_ID", "1532594541742395425")
LAST_DISCORD_MSG_ID = None
LAST_TG_CHAT_ID = None

# Default runtime state
ACTIVE_CDK = os.getenv("PUPUX_CDK", "")
TOKEN_LIMIT = int(os.getenv("PUPUX_TOKEN_LIMIT", "10"))
PAYMENT_METHOD = "kakao"  # Hardcoded to Kakao pay
AUTHORIZED_WORKERS = {"sleepu69", "royfumbler"}  # Username whitelist (lowercase)

STOCK_FILE = "token_stock.txt"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

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

async def push_stock_to_discord_db(http):
    if not DISCORD_TOKEN or not DISCORD_DB_CHANNEL_ID:
        return
    url = f"https://discord.com/api/v9/channels/{DISCORD_DB_CHANNEL_ID}/messages"
    headers = {"Authorization": DISCORD_TOKEN}
    tokens = load_stock()
    
    content_payload = f"📦 **Token Stock DB Backup** — `{len(tokens)}` unused token(s) in pool."
    
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
    if not DISCORD_TOKEN or not DISCORD_DB_CHANNEL_ID:
        return
    url = f"https://discord.com/api/v9/channels/{DISCORD_DB_CHANNEL_ID}/messages?limit=10"
    headers = {"Authorization": DISCORD_TOKEN}
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
                await send_tg_message(http, chat_id, f"{caption}\n\n🖼️ QR Image: {photo_url}")
            return res
    except Exception:
        await send_tg_message(http, chat_id, f"{caption}\n\n🖼️ QR Image: {photo_url}")

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
        await send_tg_message(http, chat_id, "❌ **CDK Key is not configured yet!**\nPlease set it using `/setcdk <CDK_KEY>`.")
        return

    init_res = await send_tg_message(
        http, chat_id,
        f"⏳ **Processing {len(tokens)} Kakao Pay Access Token(s)...**\n"
        f"🔑 CDK: `{ACTIVE_CDK[:6]}...` | Limit: `{TOKEN_LIMIT}`"
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
                    await edit_tg_message(http, chat_id, status_msg_id, f"❌ **API Submission Failed**\nReason: `{error_detail}`")
                else:
                    await send_tg_message(http, chat_id, f"❌ **API Submission Failed**\nReason: `{error_detail}`")
                return

            tasks = res.get("tasks", [])
            submitted_count = res.get("submitted", 0)
    except Exception as err:
        if status_msg_id:
            await edit_tg_message(http, chat_id, status_msg_id, f"❌ **Connection Error**: Failed to reach Pupux API (`{err}`)")
        else:
            await send_tg_message(http, chat_id, f"❌ **Connection Error**: Failed to reach Pupux API (`{err}`)")
        return

    if not tasks:
        if status_msg_id:
            await edit_tg_message(http, chat_id, status_msg_id, "❌ No tasks returned from API submission.")
        return

    if status_msg_id:
        await edit_tg_message(http, chat_id, status_msg_id, f"⏳ **Submitted {submitted_count} Kakao Pay tasks.** Polling results...")

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
                            f"📦 **Kakao Pay Link #{num}**\n"
                            f"🆔 Task ID: `{tid}`\n"
                            f"🔗 **Payment Link**:\n`{pay_url}`"
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
                            f"❌ **Kakao Pay Link #{num} Failed** (Task ID: `{tid}`)\nReason: `{summary_fail}`"
                        )
                        pending_task_ids.discard(tid)
        except Exception as poll_err:
            logger.error(f"Polling error: {poll_err}")

    remaining_stock = len(load_stock())
    final_text = (
        f"✅ **Completed! Delivered {results_delivered}/{submitted_count} Kakao Pay Links.**\n"
        f"📦 Unused Stock Remaining: `{remaining_stock}` tokens."
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

    # Command Handling
    cmd = text.split()[0].lower() if text else ""

    if cmd == "/start":
        welcome_text = (
            "🤖 **Kakao Pay Auto Extraction Bot**\n\n"
            "📥 **Anyone can add Access Tokens to stock!**\n"
            "• Paste tokens directly or use `/tokeninput <tokens>`\n\n"
            "👑 **Commands**:\n"
            "• `/tokeninput <tokens>` — Add Access Tokens to stock\n"
            "• `/statustoken` — View current unused Access Tokens in stock\n"
            "• `/run` — Process tokens from stock for Kakao Pay extraction\n"
            "• `/setcdk <CDK_KEY>` — Set active Pupux CDK License Key\n"
            "• `/usetoken <NUMBER>` — Set max tokens per batch (default: 10)\n"
            "• `/status` — View full bot configuration & stock summary"
        )
        await send_tg_message(http, chat_id, welcome_text)
        return

    if cmd == "/status":
        cdk_display = f"`{ACTIVE_CDK}`" if ACTIVE_CDK else "❌ *Not Set* (Use `/setcdk <KEY>`)"
        workers_str = ", ".join([f"@{w}" for w in AUTHORIZED_WORKERS]) if AUTHORIZED_WORKERS else "None"
        stock_count = len(load_stock())
        msg = (
            "📊 **Bot Configuration Status**\n\n"
            f"💳 **Payment Method**: `Kakao Pay` (Hardcoded)\n"
            f"🔑 **Active CDK Key**: {cdk_display}\n"
            f"🔢 **Max Tokens Limit**: `{TOKEN_LIMIT}`\n"
            f"📦 **Stored Token Stock**: `{stock_count}` unused tokens\n"
            f"👥 **Authorized Admins**: {workers_str}\n"
        )
        await send_tg_message(http, chat_id, msg)
        return

    if cmd == "/statustoken":
        stock_count = len(load_stock())
        await send_tg_message(http, chat_id, f"📦 **Current Token Stock**: `{stock_count}` unused Access Token(s) in pool.")
        return

    if cmd == "/tokeninput":
        parts = text.split(maxsplit=1)
        raw_arg = parts[1] if len(parts) > 1 else ""
        
        reply_to = message.get("reply_to_message")
        if not raw_arg and reply_to:
            raw_arg = reply_to.get("text", "")

        tokens = [line.strip() for line in raw_arg.splitlines() if line.strip().startswith("eyJ") or len(line.strip()) > 50]
        if not tokens:
            await send_tg_message(http, chat_id, "📥 **Token Input Mode**\nPlease paste Access Tokens right after `/tokeninput` or reply to a token message with `/tokeninput`.")
            return

        added, total_stock = add_to_stock(tokens, http=http)
        await send_tg_message(http, chat_id, f"✅ **Token Stock Updated!**\n➕ Added: `{added}` new Access Token(s)\n📦 Total Unused Stock: `{total_stock}` token(s) in pool.")
        return

    # Admin-only commands below (setcdk, usetoken, setlimit, addworker, removeworker, run)
    if cmd in ["/setcdk", "/usetoken", "/setlimit", "/addworker", "/removeworker", "/run"]:
        if not is_authorized(username):
            await send_tg_message(http, chat_id, "❌ **Access Denied**: Only authorized admins can use this command.")
            return

    if cmd == "/setcdk":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_tg_message(http, chat_id, "⚠️ **Usage**: `/setcdk <YOUR_CDK_KEY>`")
            return
        ACTIVE_CDK = parts[1].strip()
        await send_tg_message(http, chat_id, f"✅ **CDK Key Updated Successfully!**\nNew CDK: `{ACTIVE_CDK}`")
        return

    if cmd in ["/usetoken", "/setlimit"]:
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await send_tg_message(http, chat_id, "⚠️ **Usage**: `/usetoken <NUMBER>` (e.g. `/usetoken 10`)")
            return
        TOKEN_LIMIT = int(parts[1].strip())
        await send_tg_message(http, chat_id, f"✅ **Token Limit Updated!**\nMax tokens per run: `{TOKEN_LIMIT}`")
        return

    if cmd == "/addworker":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_tg_message(http, chat_id, "⚠️ **Usage**: `/addworker <@username>`")
            return
        un = parts[1].strip().lstrip('@').lower()
        AUTHORIZED_WORKERS.add(un)
        await send_tg_message(http, chat_id, f"✅ **Authorized Admin Added!**\n@{un} can now run extraction commands.")
        return

    if cmd == "/removeworker":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_tg_message(http, chat_id, "⚠️ **Usage**: `/removeworker <@username>`")
            return
        un = parts[1].strip().lstrip('@').lower()
        AUTHORIZED_WORKERS.discard(un)
        await send_tg_message(http, chat_id, f"✅ **Admin Authorization Revoked!**\n@{un} can no longer run extraction commands.")
        return

    if cmd == "/run":
        selected_tokens, remaining_stock_count = pop_from_stock(TOKEN_LIMIT, http=http)
        if not selected_tokens:
            await send_tg_message(http, chat_id, "❌ **Token Stock is Empty!** Use `/tokeninput` to add tokens first.")
            return
        await execute_extraction_batch(http, chat_id, selected_tokens)
        return

    # Direct token paste from anyone (saves to stock automatically without requiring CDK)
    raw_lines = text.splitlines()
    tokens = [line.strip() for line in raw_lines if line.strip().startswith("eyJ") or len(line.strip()) > 50]
    if tokens:
        added, total_stock = add_to_stock(tokens, http=http)
        await send_tg_message(
            http, chat_id, 
            f"✅ **{added} Access Token(s) Received & Saved to Stock!**\n"
            f"📦 Total Unused Stock: `{total_stock}` token(s)."
        )

async def poll_discord_channel(http):
    global LAST_DISCORD_MSG_ID
    if not DISCORD_TOKEN or not DISCORD_INPUT_CHANNEL_ID:
        logger.info("[Discord Sync] DISCORD_TOKEN or DISCORD_INPUT_CHANNEL_ID not set. Polling disabled.")
        return

    logger.info(f"[Discord Sync] Starting background listener for Discord Input Channel {DISCORD_INPUT_CHANNEL_ID} (2s interval)...")
    headers = {"Authorization": DISCORD_TOKEN}
    url = f"https://discord.com/api/v9/channels/{DISCORD_INPUT_CHANNEL_ID}/messages?limit=10"
    
    # Baseline fetch
    try:
        async with http.get(url, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                msgs = await resp.json()
                if msgs and isinstance(msgs, list):
                    LAST_DISCORD_MSG_ID = msgs[0].get("id")
                    logger.info(f"[Discord Sync] Baseline Message ID: {LAST_DISCORD_MSG_ID}")
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

                            extracted = extract_access_tokens_from_text(content)
                            if extracted:
                                added, total_stock = add_to_stock(extracted, http=http)
                                logger.info(f"[Discord Sync] ✅ Extracted {added} token(s) from Discord (@{author}). Total stock: {total_stock}")

                            LAST_DISCORD_MSG_ID = msg_id
                elif resp.status == 401:
                    logger.error("[Discord Sync] ❌ Invalid Discord Token! HTTP 401 Unauthorized.")
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
                print(f"❌ Error: Invalid Telegram BOT_TOKEN: {BOT_TOKEN}")
                return
            bot_info = me_json.get("result", {})
            print(f"✅ Telegram Bot Connected Successfully: @{bot_info.get('username')} ({bot_info.get('first_name')})")

        # Restore Token Stock from Discord DB Channel on startup
        await restore_stock_from_discord_db(http)

        # Start Discord Channel Listener Task
        asyncio.create_task(poll_discord_channel(http))

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
