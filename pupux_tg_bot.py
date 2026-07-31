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

import json
import re

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8845844055:AAHo-MDyyhRjX0SkHebQ9AjM-TSGLqG0Ap4")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
MASI_API_BASE = "https://masi.cc.cd"

PROXY_URL = "http://sleepiness29:pmfMiEZSvK@66.93.161.197:50100"  # Hardcoded US Proxy
TOKEN_LIMIT = int(os.getenv("TOKEN_LIMIT", "10"))
PAYMENT_METHOD = "kakao"  # Hardcoded to Kakao pay
AUTHORIZED_WORKERS = {"sleepu69", "royfumbler"}  # Initial authorized admins (lowercase)
STOCK_FILE = "token_stock.txt"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

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

    logger.info(f"[Pure-HTTP Auth] Logging in {email} via Proxy ({PROXY_URL.split('@')[-1]})...")
    try:
        async with AsyncSession(impersonate="safari15_5", proxy=PROXY_URL if PROXY_URL else None, timeout=25) as session:
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
                        if plan.lower() in ("plus", "team", "pro"):
                            await send_tg_message(
                                http, chat_id, 
                                f"`{email}` (**{plan.upper()}**):\n\n"
                                f"**Access Token**:\n`{token}`\n\n"
                                f"Account is already **{plan.upper()}**! Skipped Kakao Pay link extraction."
                            )
                        else:
                            await send_tg_message(
                                http, chat_id, 
                                f"`{email}` (**{plan.upper()}**):\n\n"
                                f"**Access Token**:\n`{token}`"
                            )
                            if ACTIVE_CDK:
                                asyncio.create_task(execute_extraction_batch(http, chat_id, [token]))
                            else:
                                await send_tg_message(http, chat_id, "**CDK Key is not set!** Please run `/setcdk YOUR_CDK_KEY` in Telegram to enable Kakao Pay link extraction.")
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
    global ACTIVE_CDK

    if not ACTIVE_CDK:
        await send_tg_message(http, chat_id, "**CDK Key is not configured yet!**\nPlease set it using `/setcdk <CDK_KEY>`.")
        return

    init_res = await send_tg_message(
        http, chat_id,
        f"**Extracting Kakao Pay Link for {len(tokens)} token(s)...**\n"
        f"CDK: `{ACTIVE_CDK[:6]}...`"
    )
    status_msg_id = init_res.get("result", {}).get("message_id") if init_res else None

    headers = {
        "X-CDK": ACTIVE_CDK,
        "Content-Type": "application/json"
    }

    results_delivered = 0
    for idx, token in enumerate(tokens, 1):
        try:
            # 1. Create Job: POST https://masi.cc.cd/v1/kakao/jobs
            create_payload = {"access_token": token}
            logger.info(f"[Masi API] Submitting token #{idx} to {MASI_API_BASE}/v1/kakao/jobs with CDK {ACTIVE_CDK[:6]}...")
            async with http.post(f"{MASI_API_BASE}/v1/kakao/jobs", headers=headers, json=create_payload, timeout=30) as resp:
                resp_text = await resp.text()
                logger.info(f"[Masi API] Create job status={resp.status}, body={resp_text}")
                try:
                    res = json.loads(resp_text)
                except Exception:
                    res = {}

                if resp.status not in (200, 201, 202) or not res.get("ok"):
                    err_msg = res.get("error") or res.get("detail") or f"HTTP {resp.status}: {resp_text[:100]}"
                    await send_tg_message(http, chat_id, f"**Job Submission Failed for Token #{idx}**\nReason: `{err_msg}`")
                    continue

                job_info = res.get("job") or {}
                job_id = job_info.get("job_id")

            if not job_id:
                await send_tg_message(http, chat_id, f"**Job Submission Error for Token #{idx}**: No job_id returned.")
                continue

            if status_msg_id:
                await edit_tg_message(http, chat_id, status_msg_id, f"**Job #{idx} Queued (ID: `{job_id}`)**. Extracting link...")

            # 2. Poll Job Status: GET https://masi.cc.cd/v1/kakao/jobs/{job_id}
            poll_headers = {"X-CDK": ACTIVE_CDK}
            start_poll = time.time()
            extracted_link = None

            while time.time() - start_poll < 120:  # Timeout after 2 minutes per job
                await asyncio.sleep(2.5)
                try:
                    async with http.get(f"{MASI_API_BASE}/v1/kakao/jobs/{job_id}", headers=poll_headers, timeout=30) as p_resp:
                        p_text = await p_resp.text()
                        try:
                            p_res = json.loads(p_text)
                        except Exception:
                            p_res = {}
                        job_data = p_res.get("job") or {}
                        st = job_data.get("status")
                        logger.info(f"[Masi API] Poll job {job_id} status={st}, body={p_text}")

                        if st == "completed":
                            output = job_data.get("output") or {}
                            extracted_link = output.get("long_url")
                            break
                        elif st in ("failed", "canceled", "cancelled"):
                            err_reason = job_data.get("error") or st
                            await send_tg_message(http, chat_id, f"**Extraction Failed for Token #{idx}** (Job ID: `{job_id}`)\nReason: `{err_reason}`")
                            break
                except Exception as poll_err:
                    logger.error(f"Polling error for job {job_id}: {poll_err}")

            if extracted_link:
                results_delivered += 1
                msg_text = (
                    f"**Access Token**:\n`{token}`\n\n"
                    f"**Payment Link**:\n`{extracted_link}`"
                )
                await send_tg_message(http, chat_id, msg_text)

        except Exception as job_err:
            logger.error(f"Job execution error for token #{idx}: {job_err}")
            await send_tg_message(http, chat_id, f"**Extraction Error for Token #{idx}**: `{job_err}`")

    final_text = f"**Completed! Delivered {results_delivered}/{len(tokens)} Kakao Pay Link(s).**"
    if status_msg_id:
        await edit_tg_message(http, chat_id, status_msg_id, final_text)
    else:
        await send_tg_message(http, chat_id, final_text)

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
            "**Kakao Pay Instant Link Extractor**\n\n"
            "**Quick Kakao Pay Link Generation**:\n"
            "• Simply paste `email|password|2fa_secret` or send `/run email|password|2fa_secret`!\n"
            "• Pure-HTTP authenticates in 1-2s and delivers your **Kakao Pay Payment Link** directly!\n\n"
            "**Commands**:\n"
            "• `/run <email|pass|2fa>` — Extract Kakao Pay Payment Link directly\n"
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
                headers = {"X-CDK": ACTIVE_CDK}
                async with http.get(f"{MASI_API_BASE}/v1/cdk/status", headers=headers, timeout=10) as cdk_resp:
                    cdk_res = await cdk_resp.json()
                    if cdk_res.get("ok"):
                        stats = cdk_res.get("cdk") or {}
                        rem = stats.get("remaining_uses", "N/A")
                        tot = stats.get("total_uses", "N/A")
                        avail = stats.get("available_uses", "N/A")
                        pend = stats.get("pending_uses", "N/A")
                        cdk_info_text = (
                            f"\n**CDK Quota Stats**:\n"
                            f"• Remaining Uses: `{rem}` / `{tot}`\n"
                            f"• Available Uses: `{avail}`\n"
                            f"• Pending Uses: `{pend}`\n"
                        )
            except Exception as cdk_err:
                logger.warning(f"Failed to fetch CDK status: {cdk_err}")

        msg = (
            "**Bot Configuration Status**\n\n"
            f"**API Provider**: `https://masi.cc.cd` (Pure Extraction API)\n"
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
