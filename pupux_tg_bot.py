import asyncio
import aiohttp
import os
import sys
import logging
from telethon import TelegramClient, events, Button

# --- CONFIGURATION ---
BOT_TOKEN = "8711939395:AAFqMmnEZaVhJ2kk04aLft2llUP8iDOU8G8"
API_ID = int(os.getenv("TELEGRAM_API_ID", "2040"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "b18441a126e1277d6c2e0445f3e00a3")

PUPUX_API_BASE = "https://ai.pupux.xyz/api/paylinks"

# Default runtime state
ACTIVE_CDK = os.getenv("PUPUX_CDK", "")
TOKEN_LIMIT = int(os.getenv("PUPUX_TOKEN_LIMIT", "10"))
PAYMENT_METHOD = "kakao"  # Hardcoded to Kakao pay
AUTHORIZED_WORKERS = {"sleepu69", "royfumbler"}  # Username whitelist (lowercase)

STOCK_FILE = "token_stock.txt"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = TelegramClient('pupux_kakao_bot', API_ID, API_HASH)

def load_stock():
    if not os.path.exists(STOCK_FILE):
        return []
    with open(STOCK_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def save_stock(tokens):
    with open(STOCK_FILE, "w", encoding="utf-8") as f:
        for t in tokens:
            f.write(f"{t}\n")

def add_to_stock(new_tokens):
    existing = load_stock()
    existing_set = set(existing)
    added = 0
    for t in new_tokens:
        if t not in existing_set:
            existing.append(t)
            existing_set.add(t)
            added += 1
    save_stock(existing)
    return added, len(existing)

def pop_from_stock(count):
    existing = load_stock()
    selected = existing[:count]
    remaining = existing[count:]
    save_stock(remaining)
    return selected, len(remaining)

def is_authorized(username):
    if not username:
        return False
    return username.lower().lstrip('@') in AUTHORIZED_WORKERS

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    workers_list = ", ".join([f"@{w}" for w in AUTHORIZED_WORKERS])
    welcome_text = (
        "🤖 **Kakao Pay Auto Extraction Bot**\n\n"
        f"📥 **Authorized Admins/Workers**: {workers_list}\n\n"
        "👑 **Commands**:\n"
        "• `/tokeninput <tokens>` — Add Access Tokens to stock\n"
        "• `/statustoken` — View current unused Access Tokens in stock\n"
        "• `/run` — Process tokens from stock for Kakao Pay extraction\n"
        "• `/setcdk <CDK_KEY>` — Set active Pupux CDK License Key\n"
        "• `/usetoken <NUMBER>` — Set max tokens per batch (default: 10)\n"
        "• `/addworker <@username>` — Authorize user/admin\n"
        "• `/removeworker <@username>` — Revoke user authorization\n"
        "• `/status` — View full bot configuration & stock summary"
    )
    await event.respond(welcome_text)

@bot.on(events.NewMessage(pattern='/status'))
async def status_handler(event):
    cdk_display = f"`{ACTIVE_CDK}`" if ACTIVE_CDK else "❌ *Not Set* (Use `/setcdk <KEY>`)"
    workers_str = ", ".join([f"@{w}" for w in AUTHORIZED_WORKERS]) if AUTHORIZED_WORKERS else "None"
    stock_count = len(load_stock())
    msg = (
        "📊 **Bot Configuration Status**\n\n"
        f"💳 **Payment Method**: `Kakao Pay` (Hardcoded)\n"
        f"🔑 **Active CDK Key**: {cdk_display}\n"
        f"🔢 **Max Tokens Limit**: `{TOKEN_LIMIT}`\n"
        f"📦 **Stored Token Stock**: `{stock_count}` unused tokens\n"
        f"👥 **Authorized Users**: {workers_str}\n"
    )
    await event.respond(msg)

@bot.on(events.NewMessage(pattern='/statustoken'))
async def statustoken_handler(event):
    sender = await event.get_sender()
    username = getattr(sender, 'username', '') or ''
    if not is_authorized(username):
        await event.respond("❌ **Access Denied**: You are not authorized to check token status.")
        return

    stock_count = len(load_stock())
    await event.respond(f"📦 **Current Token Stock**: `{stock_count}` unused Access Token(s) in pool.")

@bot.on(events.NewMessage(pattern=r'/tokeninput(?:\s+([\s\S]+))?'))
async def tokeninput_handler(event):
    sender = await event.get_sender()
    username = getattr(sender, 'username', '') or ''
    if not is_authorized(username):
        await event.respond("❌ **Access Denied**: Only authorized users (like `@Sleepu69` and `@Royfumbler`) can input tokens.")
        return

    raw_arg = event.pattern_match.group(1) or ""
    
    # If tokens attached or in reply
    if not raw_arg and event.is_reply:
        reply_msg = await event.get_reply_message()
        if reply_msg and reply_msg.text:
            raw_arg = reply_msg.text

    tokens = [line.strip() for line in raw_arg.splitlines() if line.strip().startswith("eyJ") or len(line.strip()) > 50]
    
    if not tokens:
        await event.respond(
            "📥 **Token Input Mode**\n"
            "Please paste Access Tokens right after `/tokeninput` or reply to a token list with `/tokeninput`."
        )
        return

    added, total_stock = add_to_stock(tokens)
    await event.respond(
        f"✅ **Token Stock Updated!**\n"
        f"➕ Added: `{added}` new Access Token(s)\n"
        f"📦 Total Unused Stock: `{total_stock}` token(s) in pool."
    )

@bot.on(events.NewMessage(pattern=r'/addworker(?:\s+(.+))?'))
async def addworker_handler(event):
    sender = await event.get_sender()
    username = getattr(sender, 'username', '') or ''
    if not is_authorized(username):
        await event.respond("❌ Access Denied.")
        return

    arg = event.pattern_match.group(1)
    if not arg:
        await event.respond("⚠️ **Usage**: `/addworker <@username>`")
        return
    un = arg.strip().lstrip('@').lower()
    AUTHORIZED_WORKERS.add(un)
    await event.respond(f"✅ **Authorized User Added!**\n@{un} can now use the bot.")

@bot.on(events.NewMessage(pattern=r'/removeworker(?:\s+(.+))?'))
async def removeworker_handler(event):
    sender = await event.get_sender()
    username = getattr(sender, 'username', '') or ''
    if not is_authorized(username):
        await event.respond("❌ Access Denied.")
        return

    arg = event.pattern_match.group(1)
    if not arg:
        await event.respond("⚠️ **Usage**: `/removeworker <@username>`")
        return
    un = arg.strip().lstrip('@').lower()
    AUTHORIZED_WORKERS.discard(un)
    await event.respond(f"✅ **User Authorization Revoked!**\n@{un} can no longer use the bot.")

@bot.on(events.NewMessage(pattern=r'/setcdk(?:\s+(.+))?'))
async def setcdk_handler(event):
    sender = await event.get_sender()
    username = getattr(sender, 'username', '') or ''
    if not is_authorized(username):
        await event.respond("❌ Access Denied.")
        return

    global ACTIVE_CDK
    arg = event.pattern_match.group(1)
    if not arg:
        await event.respond("⚠️ **Usage**: `/setcdk <YOUR_CDK_KEY>`")
        return
    ACTIVE_CDK = arg.strip()
    await event.respond(f"✅ **CDK Key Updated Successfully!**\nNew CDK: `{ACTIVE_CDK}`")

@bot.on(events.NewMessage(pattern=r'/(?:usetoken|setlimit)(?:\s+(.+))?'))
async def usetoken_handler(event):
    sender = await event.get_sender()
    username = getattr(sender, 'username', '') or ''
    if not is_authorized(username):
        await event.respond("❌ Access Denied.")
        return

    global TOKEN_LIMIT
    arg = event.pattern_match.group(1)
    if not arg or not arg.strip().isdigit():
        await event.respond("⚠️ **Usage**: `/usetoken <NUMBER>` (e.g. `/usetoken 10`)")
        return
    TOKEN_LIMIT = int(arg.strip())
    await event.respond(f"✅ **Token Limit Updated!**\nMax tokens per run: `{TOKEN_LIMIT}`")

async def execute_extraction_batch(event, tokens):
    global ACTIVE_CDK, TOKEN_LIMIT

    if not ACTIVE_CDK:
        await event.respond("❌ **CDK Key is not configured yet!**\nPlease set it using `/setcdk <CDK_KEY>`.")
        return

    status_msg = await event.respond(
        f"⏳ **Processing {len(tokens)} Kakao Pay Access Token(s)...**\n"
        f"🔑 CDK: `{ACTIVE_CDK[:6]}...` | Limit: `{TOKEN_LIMIT}`"
    )

    # 1. Submit Tasks Batch to Pupux API
    async with aiohttp.ClientSession() as http:
        payload = {
            "payment_method": PAYMENT_METHOD,
            "cdk": ACTIVE_CDK,
            "access_tokens": tokens
        }
        
        try:
            async with http.post(f"{PUPUX_API_BASE}/tasks/batch", json=payload, timeout=20) as resp:
                res = await resp.json()
                if not res.get("ok"):
                    error_detail = res.get("detail", "Unknown error")
                    await status_msg.edit(f"❌ **API Submission Failed**\nReason: `{error_detail}`")
                    return

                tasks = res.get("tasks", [])
                submitted_count = res.get("submitted", 0)
        except Exception as err:
            await status_msg.edit(f"❌ **Connection Error**: Failed to reach Pupux API (`{err}`)")
            return

        if not tasks:
            await status_msg.edit("❌ No tasks returned from API submission.")
            return

        await status_msg.edit(f"⏳ **Submitted {submitted_count} Kakao Pay tasks.** Polling results...")

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
                                try:
                                    await bot.send_file(event.chat_id, qr_url, caption=card_text)
                                except Exception:
                                    await bot.send_message(event.chat_id, card_text)
                            else:
                                await bot.send_message(event.chat_id, card_text)

                            pending_task_ids.discard(tid)
                            results_delivered += 1

                        elif st in ["failed", "cancelled", "stale"]:
                            num = task_num_map.get(tid, 1)
                            fail_obj = item.get("failure") or {}
                            summary_fail = fail_obj.get("summary") or st
                            await bot.send_message(
                                event.chat_id, 
                                f"❌ **Kakao Pay Link #{num} Failed** (Task ID: `{tid}`)\nReason: `{summary_fail}`"
                            )
                            pending_task_ids.discard(tid)
            except Exception as poll_err:
                logger.error(f"Polling error: {poll_err}")

    remaining_stock = len(load_stock())
    await status_msg.edit(
        f"✅ **Completed! Delivered {results_delivered}/{submitted_count} Kakao Pay Links.**\n"
        f"📦 Unused Stock Remaining: `{remaining_stock}` tokens."
    )

@bot.on(events.NewMessage(pattern='/run'))
async def run_handler(event):
    sender = await event.get_sender()
    username = getattr(sender, 'username', '') or ''
    if not is_authorized(username):
        await event.respond("❌ Access Denied.")
        return

    # Pop up to TOKEN_LIMIT tokens from stored stock file
    selected_tokens, remaining_stock_count = pop_from_stock(TOKEN_LIMIT)
    if not selected_tokens:
        await event.respond("❌ **Token Stock is Empty!** Use `/tokeninput` to add tokens first.")
        return

    await execute_extraction_batch(event, selected_tokens)

@bot.on(events.NewMessage)
async def process_tokens_message(event):
    text = event.text.strip() if event.text else ""
    if not text or text.startswith('/'):
        return

    sender = await event.get_sender()
    username = getattr(sender, 'username', '') or ''
    if not is_authorized(username):
        await event.respond("❌ **Access Denied**: Only authorized users (like `@Sleepu69` and `@Royfumbler`) can use this bot.")
        return

    # Extract tokens starting with eyJ
    raw_lines = text.splitlines()
    tokens = [line.strip() for line in raw_lines if line.strip().startswith("eyJ") or len(line.strip()) > 50]
    
    if not tokens:
        return

    # Automatically add to stock and prompt or execute
    added, total_stock = add_to_stock(tokens)
    
    # Take TOKEN_LIMIT from stock and process immediately
    selected_tokens, remaining_stock_count = pop_from_stock(TOKEN_LIMIT)
    if selected_tokens:
        await execute_extraction_batch(event, selected_tokens)

async def main():
    print("[System] Connecting Kakao Pay Bot to Telegram...")
    await bot.start(bot_token=BOT_TOKEN)
    print("[System] Bot is running and listening for messages 24/7.")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
