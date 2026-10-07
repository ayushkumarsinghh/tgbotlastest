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
BOT_TOKEN = os.getenv("BOT_TOKEN", "8902527460:AAGpm3RWI1dH_o9KnjkOJTWHeEVTHVFM5KY")
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
PUPUX_API_BASE = "https://api.int31.space"
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
PROXIES_FILE = "proxies.txt"

def parse_proxy_line(line_str):
    line_str = line_str.strip()
    if not line_str or line_str.startswith("#"):
        return None
    
    # URL format: http://user:pass@host:port or https://...
    if "@" in line_str and ("://" in line_str or line_str.startswith("http")):
        m = re.match(r'(?:https?://)?([^:]+):([^@]+)@([^:]+):(\d+)', line_str)
        if m:
            user, pwd, host, port = m.groups()
            pool_url = f"http://{user}:{pwd}@{host}:{port}"
            exlink_str = f"{host}:{port}:{user}:{pwd}"
            return pool_url, exlink_str

    # 4-part format: host:port:user:pass
    parts = line_str.split(":")
    if len(parts) >= 4:
        host = parts[0].strip()
        port = parts[1].strip()
        user = parts[2].strip()
        pwd = parts[3].strip()
        if port.isdigit():
            pool_url = f"http://{user}:{pwd}@{host}:{port}"
            exlink_str = f"{host}:{port}:{user}:{pwd}"
            return pool_url, exlink_str

    return None

def save_proxies_to_file(exlink_list):
    try:
        with open(PROXIES_FILE, "w", encoding="utf-8") as f:
            for p in exlink_list:
                f.write(f"{p}\n")
    except Exception as e:
        logger.error(f"Failed to save proxies to file: {e}")

def load_proxies_from_file():
    if not os.path.exists(PROXIES_FILE):
        return None, None
    try:
        pool_list = []
        exlink_list = []
        with open(PROXIES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parsed = parse_proxy_line(line)
                if parsed:
                    pool_list.append(parsed[0])
                    exlink_list.append(parsed[1])
        if pool_list and exlink_list:
            return pool_list, exlink_list
    except Exception as e:
        logger.error(f"Failed to load proxies from file: {e}")
    return None, None

# Load persisted custom proxies if file exists
_loaded_pool, _loaded_exlink = load_proxies_from_file()
if _loaded_pool and _loaded_exlink:
    PROXY_POOL = _loaded_pool
    EXLINK_PROXIES = _loaded_exlink
    PROXY_URL = PROXY_POOL[0]

TOKEN_LIMIT = int(os.getenv("TOKEN_LIMIT", "10"))
PAYMENT_METHOD = "upi"  # Hardcoded to UPI pay
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

async def process_and_extract_credentials(text, http=None, chat_id=None, extract_payment=False):
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
                        msg = (
                            f"✅ **Login Successful!**\n\n"
                            f"📧 **Email**: `{email}`\n"
                            f"⭐ **Plan**: **{plan.upper()}**\n\n"
                            f"🔑 **Access Token** *(tap to copy)*:\n"
                            f"`{token}`"
                        )
                        await send_tg_message(http, chat_id, msg)

                        if extract_payment:
                            if plan.lower() in ("plus", "team", "pro"):
                                await send_tg_message(
                                    http, chat_id, 
                                    f"`{email}` (**{plan.upper()}**):\n\n"
                                    f"Account is already **{plan.upper()}**! Skipped UPI link extraction."
                                )
                            else:
                                await send_tg_message(
                                    http, chat_id, 
                                    f"⏳ Extracting UPI payment link for `{email}`..."
                                )
                                if ACTIVE_CDK:
                                    asyncio.create_task(execute_extraction_batch(http, chat_id, [token]))
                                else:
                                    await send_tg_message(http, chat_id, "**CDK Key is not set!** Please run `/cdk YOUR_CDK_KEY` in Telegram to enable UPI link extraction.")
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
    return added, len(existing)

def pop_from_stock(count, http=None):
    existing = load_stock()
    selected = existing[:count]
    remaining = existing[count:]
    save_stock(remaining)
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
            form.add_field("photo", io.BytesIO(img_data), filename="upi_qr.png", content_type="image/png")
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

async def validate_cdk(http, cdk):
    url = f"{PUPUX_API_BASE}/public/api/checkout/cdk/validate"
    try:
        headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        async with http.post(url, json={"cdk": cdk.strip()}, headers=headers, timeout=10) as resp:
            try:
                data = await resp.json()
            except Exception:
                data = {"detail": await resp.text()}
            return resp.status, data
    except Exception as e:
        return 500, {"detail": str(e)}

async def extract_upi_via_api(http, chat_id, token, cdk_to_use, status_msg_id=None):
    submit_url = f"{PUPUX_API_BASE}/public/api/checkout/flow/submit-batch"
    
    proxy_choice = random.choice(PROXY_POOL) if PROXY_POOL else None
    req_item = {
        "cdk": cdk_to_use.strip(),
        "accessToken": token.strip(),
        "paymentMethodType": PAYMENT_METHOD.upper(),  # "UPI"
        "maxAmountCents": 0,
    }
    if proxy_choice:
        req_item["proxyUrl"] = proxy_choice

    payload = {"requests": [req_item]}
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

    try:
        logger.info(f"[int31 API] Submitting checkout task with CDK {cdk_to_use[:6]}...")
        async with http.post(submit_url, json=payload, headers=headers, timeout=20) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                try:
                    err_json = json.loads(err_text)
                    err_msg = err_json.get("detail") or err_json.get("title") or err_text
                except Exception:
                    err_msg = err_text
                logger.error(f"[int31 API] Submit error (HTTP {resp.status}): {err_msg}")
                await send_tg_message(http, chat_id, f"❌ **Task Submission Error** (HTTP {resp.status}):\n`{err_msg}`")
                return False

            submit_data = await resp.json()

        results = submit_data.get("results", [])
        if not results:
            await send_tg_message(http, chat_id, "❌ **Task Submission Failed**: Empty result list received from backend.")
            return False

        first_res = results[0]
        outcome = first_res.get("outcome")
        if outcome in ("REJECTED", "UNKNOWN"):
            err_detail = first_res.get("error") or f"Submission outcome: {outcome}"
            logger.error(f"[int31 API] Item rejected: {err_detail}")
            await send_tg_message(http, chat_id, f"❌ **Task Rejected by API**:\n`{err_detail}`")
            return False

        task_info = first_res.get("task") or {}
        task_id = task_info.get("taskId")
        if not task_id:
            await send_tg_message(http, chat_id, "❌ **Task Submission Error**: Missing taskId in response.")
            return False

        logger.info(f"[int31 API] Task accepted (ID: {task_id}, Outcome: {outcome})")
        if status_msg_id:
            await edit_tg_message(http, chat_id, status_msg_id, f"⏳ **Task Accepted ({outcome})**\nTask ID: `{task_id[:8]}...`\nGenerating UPI payment link...")

        # Poll task status: GET /public/api/checkout/flow/{taskId}
        poll_url = f"{PUPUX_API_BASE}/public/api/checkout/flow/{task_id}"
        start_time = time.time()

        while time.time() - start_time < 300:  # 5 minutes timeout
            await asyncio.sleep(4)
            try:
                async with http.get(poll_url, headers=headers, timeout=15) as poll_resp:
                    if poll_resp.status != 200:
                        logger.warning(f"[int31 API] Poll returned HTTP {poll_resp.status}")
                        continue
                    snap = await poll_resp.json()
            except Exception as pe:
                logger.warning(f"[int31 API] Poll exception: {pe}")
                continue

            status = snap.get("status")
            step = snap.get("currentStep", "")
            prog = snap.get("progressPercent", 0)

            logger.info(f"[int31 API] Task {task_id[:8]} -> Status: {status}, Step: {step}, Progress: {prog}%")

            if status in ("QUEUED", "RUNNING"):
                if status_msg_id and step:
                    try:
                        await edit_tg_message(http, chat_id, status_msg_id, f"⏳ **Extracting UPI Link...** ({prog}%)\n_Step: {step}_\nTask ID: `{task_id[:8]}...`")
                    except Exception:
                        pass

            elif status == "SUCCEEDED":
                result = snap.get("result") or {}
                artifact = result.get("paymentArtifact") or {}

                hosted_url = result.get("hostedUrl")
                jump_url = artifact.get("url")
                processor_url = artifact.get("processorUrl")
                instructions_url = artifact.get("hostedInstructionsUrl")
                qr_data = artifact.get("data")
                qr_img = artifact.get("imageUrlPng") or artifact.get("imageUrlSvg")

                # Strictly extract the direct payment link (payment.stripe.com / processor link) - avoid generic checkout link
                pay_link = None
                for candidate in [processor_url, jump_url, instructions_url]:
                    if candidate and ("payment.stripe" in candidate or "pay.stripe" in candidate):
                        pay_link = candidate
                        break

                if not pay_link and processor_url and "checkout.stripe" not in processor_url:
                    pay_link = processor_url

                if not pay_link:
                    for candidate in [jump_url, instructions_url]:
                        if candidate and "checkout.stripe" not in candidate:
                            pay_link = candidate
                            break

                if not pay_link and qr_data and (qr_data.startswith("http") or qr_data.startswith("upi://")):
                    pay_link = qr_data

                if not pay_link:
                    pay_link = processor_url or jump_url or instructions_url

                caption = f"🇮🇳 **UPI Payment Link Ready (India)**\nTask ID: `{task_id[:8]}`"
                if pay_link:
                    caption += f"\n\n🔗 **Payment Link**:\n`{pay_link}`"

                if qr_data and not pay_link:
                    caption += f"\n\n📱 **UPI QR Data / VPA**:\n`{qr_data}`"

                if qr_img:
                    await send_tg_photo(http, chat_id, qr_img, caption=caption)
                elif qr_data and qr_data.startswith("data:image"):
                    await send_tg_photo(http, chat_id, qr_data, caption=caption)
                else:
                    await send_tg_message(http, chat_id, caption)

                return True

            elif status == "FAILED":
                fail_code = snap.get("failureCode") or "UNKNOWN_FAILURE"
                fail_type = snap.get("failureType") or ""
                err_display = f"{fail_code} ({fail_type})" if fail_type else fail_code
                logger.error(f"[int31 API] Task {task_id} failed: {err_display}")
                await send_tg_message(http, chat_id, f"❌ **UPI Extraction Failed**:\n`{err_display}`\nTask ID: `{task_id}`")
                return False

            elif status == "CANCELED":
                logger.warning(f"[int31 API] Task {task_id} canceled")
                await send_tg_message(http, chat_id, f"⚠️ **Task Canceled** (Task ID: `{task_id}`)")
                return False

        await send_tg_message(http, chat_id, f"⏱️ **Extraction Timed Out** (5 minutes exceeded for Task `{task_id[:8]}`)")
        return False

    except Exception as e:
        logger.error(f"[int31 API] Exception: {e}")
        await send_tg_message(http, chat_id, f"❌ **API Error**: `{e}`")
        return False

async def execute_extraction_batch(http, chat_id, tokens, cdk_override=None):
    global ACTIVE_CDK

    cdk_to_use = cdk_override or ACTIVE_CDK
    if not cdk_to_use:
        await send_tg_message(http, chat_id, "🔑 **CDK Key Required!**\nPlease enter your CDK key using `/cdk YOUR_CDK_KEY` or provide it in `/run email|pass|2fa YOUR_CDK`.")
        return

    init_res = await send_tg_message(
        http, chat_id,
        f"🇮🇳 **Starting UPI Link Extraction for {len(tokens)} token(s)...**\n"
        f"CDK: `{cdk_to_use[:6]}...`"
    )
    status_msg_id = init_res.get("result", {}).get("message_id") if init_res else None

    success_count = 0
    for tok in tokens:
        ok = await extract_upi_via_api(http, chat_id, tok, cdk_to_use, status_msg_id)
        if ok:
            success_count += 1

    final_msg = f"**Completed! Delivered {success_count}/{len(tokens)} UPI Link(s).**"
    if status_msg_id:
        await edit_tg_message(http, chat_id, status_msg_id, final_msg)
    else:
        await send_tg_message(http, chat_id, final_msg)

async def handle_update(http, update):
    global ACTIVE_CDK, AUTHORIZED_WORKERS, LAST_TG_CHAT_ID, PROXY_POOL, EXLINK_PROXIES, PROXY_URL

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
            "🤖 **ChatGPT Account & Access Token Bot**\n\n"
            "**Access Token Generation** *(Default)*:\n"
            "• Simply paste `email|password|2fa_secret` or send `/token <credentials>`\n"
            "• Pure-HTTP authenticates in 1-2s and delivers your **Access Token** (tap to copy) and Account Plan!\n"
            "• Zero CDK consumption.\n\n"
            "**Commands**:\n"
            "• Paste `email|pass|2fa` — Instant login & Access Token output\n"
            "• `/token <email|pass|2fa>` — Generate & copy Access Token\n"
            "• `/check <email|pass|2fa>` — Check account plan (Plus/Free) & get Access Token\n"
            "• `/run <email|pass|2fa>` — Extract UPI Payment Link & QR (India 🇮🇳, uses CDK)\n"
            "• `/cdk [KEY]` — View CDK balance/status or set a new CDK key\n"
            "• `/proxy <list>` — Replace active proxies with new ones\n"
            "• `/status` — View bot configuration & backend status\n"
            "• `/adduser <@username>` — Authorize a new user\n"
            "• `/removeuser <@username>` — Revoke a user's access"
        )
        await send_tg_message(http, chat_id, welcome_text)
        return

    if cmd == "/status":
        cdk_display = f"`{ACTIVE_CDK}`" if ACTIVE_CDK else "*Not Set* (Use `/cdk <KEY>`)"
        workers_str = ", ".join([f"@{w}" for w in AUTHORIZED_WORKERS]) if AUTHORIZED_WORKERS else "None"
        
        cdk_info_text = ""
        if ACTIVE_CDK:
            st_code, cdk_data = await validate_cdk(http, ACTIVE_CDK)
            if st_code == 200 and cdk_data.get("valid"):
                rem = cdk_data.get("remainingUses", 0)
                resv = cdk_data.get("reservedUses", 0)
                flow_cost = cdk_data.get("flowUses", 1)
                concur = cdk_data.get("maxConcurrent", 5)
                cdk_info_text = (
                    f"\n**CDK Balance**:\n"
                    f"• Remaining: `{rem}` | Reserved: `{resv}`\n"
                    f"• Flow Cost: `{flow_cost}` use(s) | Max Concurrency: `{concur}`\n"
                )
            else:
                detail = cdk_data.get("detail") or cdk_data.get("title") or "Invalid/Unavailable"
                cdk_info_text = f"\n**CDK Status**: `{detail}` (HTTP {st_code})\n"

        svc_info_text = ""
        try:
            async with http.get(f"{PUPUX_API_BASE}/public/api/checkout/flow/status", timeout=8) as s_resp:
                if s_resp.status == 200:
                    s_data = await s_resp.json()
                    accepting = "Yes ✅" if s_data.get("acceptingTasks") else "No ❌"
                    running = s_data.get("runningTasks", 0)
                    queued = s_data.get("queuedTasks", 0)
                    svc_info_text = f"• **Backend Queue**: `{running}` running, `{queued}` queued (Accepting: {accepting})\n"
        except Exception:
            pass

        msg = (
            "**Bot Configuration Status**\n\n"
            f"**API Provider**: `https://api.int31.space` (Public Checkout Flow API)\n"
            f"**Payment Method**: `UPI` (India 🇮🇳)\n"
            f"{svc_info_text}"
            f"**Active CDK Key**: {cdk_display}\n"
            f"**Active Proxies**: `{len(PROXY_POOL)}` loaded\n"
            f"**Authorized Users**: {workers_str}\n"
            f"{cdk_info_text}"
        )
        await send_tg_message(http, chat_id, msg)
        return

    if cmd in ["/cdk", "/setcdk"]:
        parts = text.split(maxsplit=1)
        raw_cdk = parts[1].strip() if len(parts) > 1 else ""

        if raw_cdk:
            ACTIVE_CDK = raw_cdk
            st_code, data = await validate_cdk(http, ACTIVE_CDK)
            if st_code == 200 and data.get("valid"):
                rem = data.get("remainingUses", 0)
                resv = data.get("reservedUses", 0)
                flow_cost = data.get("flowUses", 1)
                concur = data.get("maxConcurrent", 5)
                exp = data.get("expiresAt") or "Never"
                msg = (
                    f"✅ **CDK Key Updated & Verified!**\n\n"
                    f"• **Key**: `{ACTIVE_CDK}`\n"
                    f"• **Remaining Uses**: `{rem}`\n"
                    f"• **Reserved Uses**: `{resv}`\n"
                    f"• **Cost Per Flow**: `{flow_cost}` use(s)\n"
                    f"• **Max Concurrent**: `{concur}`\n"
                    f"• **Expires**: `{exp}`\n\n"
                    f"Ready for UPI checkout extraction! 🚀"
                )
            else:
                detail = data.get("detail") or data.get("title") or "Invalid or unavailable"
                msg = (
                    f"⚠️ **CDK Key Set, but validation returned notice**:\n\n"
                    f"• **Key**: `{ACTIVE_CDK}`\n"
                    f"• **Status** (HTTP {st_code}): `{detail}`\n\n"
                    f"Please verify this is a valid CDK from api.int31.space."
                )
            await send_tg_message(http, chat_id, msg)
            return
        else:
            if not ACTIVE_CDK:
                await send_tg_message(
                    http, chat_id,
                    "🔑 **No CDK Currently Active!**\n\n"
                    "**Usage**:\n"
                    "`/cdk <YOUR_CDK_KEY>`\n\n"
                    "Example:\n"
                    "`/cdk ABCD-1234-EFGH-5678`"
                )
                return

            st_code, data = await validate_cdk(http, ACTIVE_CDK)
            if st_code == 200 and data.get("valid"):
                rem = data.get("remainingUses", 0)
                resv = data.get("reservedUses", 0)
                flow_cost = data.get("flowUses", 1)
                concur = data.get("maxConcurrent", 5)
                max_tasks = data.get("maxActiveTasks", 100)
                exp = data.get("expiresAt") or "Never"
                msg = (
                    f"🔑 **Active CDK Status & Balance**\n\n"
                    f"• **Key**: `{ACTIVE_CDK}`\n"
                    f"• **Status**: Valid & Active ✅\n"
                    f"• **Remaining Uses**: `{rem}`\n"
                    f"• **Reserved Uses**: `{resv}`\n"
                    f"• **Cost Per Flow**: `{flow_cost}` use(s)\n"
                    f"• **Max Concurrent**: `{concur}`\n"
                    f"• **Max Active Tasks**: `{max_tasks}`\n"
                    f"• **Expires**: `{exp}`\n\n"
                    f"To update your CDK, send: `/cdk <NEW_KEY>`"
                )
            else:
                detail = data.get("detail") or data.get("title") or "Invalid or unavailable"
                msg = (
                    f"⚠️ **Active CDK Validation Notice** (HTTP {st_code}):\n\n"
                    f"• **Key**: `{ACTIVE_CDK}`\n"
                    f"• **Status**: `{detail}`\n\n"
                    f"To update your CDK, send: `/cdk <NEW_KEY>`"
                )
            await send_tg_message(http, chat_id, msg)
            return

    if cmd in ["/proxy", "/proxies", "/setproxy"]:
        parts = text.split(maxsplit=1)
        raw_arg = parts[1] if len(parts) > 1 else ""

        reply_to = message.get("reply_to_message")
        if not raw_arg and reply_to:
            raw_arg = reply_to.get("text", "")

        # If user types /proxy without arguments, show currently active proxies
        if not raw_arg.strip():
            preview = "\n".join([f"• `{p}`" for p in EXLINK_PROXIES[:15]])
            if len(EXLINK_PROXIES) > 15:
                preview += f"\n_...and {len(EXLINK_PROXIES) - 15} more_"
            msg = (
                f"🌐 **Current Active Proxies** (`{len(EXLINK_PROXIES)}` loaded):\n\n"
                f"{preview}\n\n"
                f"**To replace all proxies with a new list**:\n"
                f"Send `/proxy` followed by your proxies (one per line), or reply to a message containing proxies with `/proxy`.\n\n"
                f"**Accepted Formats**:\n"
                f"• `host:port:username:password`\n"
                f"• `http://username:password@host:port`"
            )
            await send_tg_message(http, chat_id, msg)
            return

        new_pool = []
        new_exlink = []
        for line in raw_arg.splitlines():
            line_clean = line.strip()
            if not line_clean:
                continue
            parsed = parse_proxy_line(line_clean)
            if parsed:
                pool_u, ex_str = parsed
                if pool_u not in new_pool:
                    new_pool.append(pool_u)
                    new_exlink.append(ex_str)

        if not new_pool:
            await send_tg_message(
                http, chat_id,
                "❌ **No valid proxies found in your input!**\n\n"
                "Please provide proxies in format:\n"
                "`host:port:username:password`\n"
                "Example:\n"
                "`us.1024proxy.io:3000:username:password`"
            )
            return

        # Replace old proxies with new ones
        PROXY_POOL = new_pool
        EXLINK_PROXIES = new_exlink
        PROXY_URL = PROXY_POOL[0]
        save_proxies_to_file(EXLINK_PROXIES)

        logger.info(f"[Proxy Manager] Replaced proxies with {len(new_pool)} new proxies by @{username}")

        preview = "\n".join([f"• `{p}`" for p in new_exlink[:10]])
        if len(new_exlink) > 10:
            preview += f"\n_...and {len(new_exlink) - 10} more_"

        success_msg = (
            f"✅ **Proxies Updated Successfully!**\n\n"
            f"Old proxies have been removed. Activated `{len(new_pool)}` new proxy/proxies for authentication and UPI extraction.\n\n"
            f"**Active Pool Preview**:\n"
            f"{preview}"
        )
        await send_tg_message(http, chat_id, success_msg)
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
                        f"✅ **Account Check Result**\n\n"
                        f"📧 **Email**: `{email}`\n"
                        f"⭐ **Plan**: **{plan.upper()}**\n\n"
                        f"🔑 **Access Token** *(tap to copy)*:\n"
                        f"`{token}`"
                    )
                    await send_tg_message(http, chat_id, msg)
                else:
                    await send_tg_message(http, chat_id, f"❌ **Check Failed**: {status_msg}")
        return

    if cmd in ["/token", "/login"]:
        parts = text.split(maxsplit=1)
        raw_arg = parts[1] if len(parts) > 1 else ""
        
        reply_to = message.get("reply_to_message")
        if not raw_arg and reply_to:
            raw_arg = reply_to.get("text", "")

        if not raw_arg:
            await send_tg_message(http, chat_id, "**Get Access Token Mode**\nPlease paste `email|pass|2fa` right after `/token` or reply to a message containing credentials with `/token`.")
            return

        tokens = await process_and_extract_credentials(raw_arg, http=http, chat_id=chat_id, extract_payment=False)
        if not tokens:
            await send_tg_message(http, chat_id, "**Could not process credentials.** Please format as: `email|password|2fa_secret`")
            return
            
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

        tokens = await process_and_extract_credentials(raw_arg, http=http, chat_id=chat_id, extract_payment=True)
        if not tokens:
            await send_tg_message(http, chat_id, "**Could not process credentials.** Please format as: `email|password|2fa_secret`")
            return
            
        return

    # Direct credential paste (email|pass|2fa) defaults to returning access token (no CDK spent)
    if "@" in text and ("|" in text or ":" in text) and not text.startswith("eyJ"):
        tokens = await process_and_extract_credentials(text, http=http, chat_id=chat_id, extract_payment=False)
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
    print(f"[System] Starting UPI Telegram Bot (Direct Telegram API)...")
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

        # Clear any stale webhook to ensure getUpdates never encounters 409 Conflict
        try:
            async with http.get(f"{TG_API}/deleteWebhook") as wh_resp:
                wh_data = await wh_resp.json()
                logger.info(f"[System] Webhook status: {wh_data.get('description', 'Cleared')}")
        except Exception as wh_err:
            logger.warning(f"[System] Could not clear webhook: {wh_err}")

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
                    else:
                        err_code = data.get("error_code")
                        err_desc = data.get("description", "")
                        logger.warning(f"[Poller] Telegram API notice ({err_code}): {err_desc}")
                        if err_code == 409 and "webhook" in err_desc.lower():
                            logger.info("[Poller] Webhook conflict detected. Auto-clearing webhook...")
                            await http.get(f"{TG_API}/deleteWebhook")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Poller exception: {e}")
                await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())
