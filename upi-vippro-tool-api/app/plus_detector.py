from __future__ import annotations

import asyncio
from typing import Any

from curl_cffi.requests import AsyncSession

from app.config import ConfigStore
from app.login_service import IMPERSONATE
from app.models import JobRecord, SessionEntry
from app.session_cache import SessionCache


class PollError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PlusDetector:
    def __init__(self, config: ConfigStore, session_cache: SessionCache) -> None:
        self.config = config
        self.session_cache = session_cache

    async def _get_session(self, cookies: dict[str, str]) -> Any:
        async with AsyncSession(impersonate=IMPERSONATE, timeout=30) as client:
            for name, value in cookies.items():
                try:
                    client.cookies.set(name, value, domain=".chatgpt.com")
                except Exception:
                    try:
                        client.cookies.set(name, value)
                    except Exception:
                        pass
            return await client.get(
                "https://chatgpt.com/api/auth/session",
                headers={
                    "Accept": "application/json",
                    "Referer": "https://chatgpt.com/",
                },
            )

    async def poll_plus(self, job: JobRecord, entry: SessionEntry) -> str:
        cfg = self.config.get()
        for _ in range(cfg.poll_budget):
            await asyncio.sleep(cfg.poll_interval_seconds)
            net_retry = 0
            while True:
                try:
                    r = await self._get_session(entry.cookies)
                    if r.status_code == 401:
                        self.session_cache.mark_invalid(job.email)
                        raise PollError("poll_session_expired")
                    if r.status_code >= 500:
                        raise OSError(f"http_{r.status_code}")
                    data = r.json() if r.status_code == 200 else {}
                    plan = ""
                    if isinstance(data, dict):
                        plan = (
                            data.get("subscription_plan")
                            or (data.get("account") or {}).get("planType")
                            or ""
                        )
                    if plan == "chatgptplusplan" or str(plan).lower() in (
                        "plus",
                        "chatgptplusplan",
                    ):
                        return "plus"
                    break
                except PollError:
                    raise
                except Exception:
                    net_retry += 1
                    if net_retry > 2:
                        raise PollError("poll_network_error")
                    await asyncio.sleep(15)
        return "free"

    async def check_plan(self, job: JobRecord, entry: SessionEntry) -> str:
        try:
            r = await self._get_session(entry.cookies)
            if r.status_code == 401:
                self.session_cache.mark_invalid(job.email)
                return "pending"
            if r.status_code != 200:
                return "pending"
            data = r.json()
            plan = ""
            if isinstance(data, dict):
                plan = (
                    data.get("subscription_plan")
                    or (data.get("account") or {}).get("planType")
                    or ""
                )
            if plan == "chatgptplusplan" or str(plan).lower() in ("plus", "chatgptplusplan"):
                return "plus"
            return "free"
        except Exception:
            return "pending"
