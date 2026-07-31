from __future__ import annotations

import asyncio
import base64
import re
import time
import uuid
from typing import Any, Optional

from app.blocklist import BlocklistService
from app.config import ConfigStore
from app.db import Database
from app.logging_setup import get_logger, log_unclassified
from app.login_service import LoginError, login as do_login
from app.models import (
    ACTIVE_STATES,
    CHECK_PLAN_STATES,
    CONCLUDED_STATES,
    HARD_ERRORS,
    RERUNNABLE_STATES,
    SOFT_ERROR_DELAYS,
    SOFT_ERRORS,
    AccountRecord,
    BotEvent,
    BotEventType,
    DispatchOverride,
    FlowMode,
    JobRecord,
    JobState,
    QRPayload,
    SessionEntry,
    TimelineEntry,
)
from app.plus_detector import PlusDetector
from app.result_writer import ResultWriter
from app.rust_bot_client import RustBotClient
from app.session_cache import SessionCache, should_reuse
from app.sse import JobStream
from app.telegram_notifier import TelegramNotifier

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
BASE32_RE = re.compile(r"^[A-Z2-7]+=*$", re.I)

VALID_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.HELD: {
        JobState.QUEUED,
        JobState.LOGGING_IN,
        JobState.SESSION_READY,
        JobState.STOPPED,
    },
    JobState.QUEUED: {
        JobState.LOGGING_IN,
        JobState.SESSION_READY,
        JobState.HELD,  # pause → hold waiting jobs
        JobState.STOPPED,
    },
    JobState.LOGGING_IN: {
        JobState.LOGGING_IN,
        JobState.SESSION_READY,
        JobState.FAILED,
        JobState.STOPPED,
        JobState.STALE,
    },
    JobState.SESSION_READY: {
        JobState.SUBMITTING_BOT,
        JobState.STOPPED,
        JobState.FAILED,
    },
    JobState.SUBMITTING_BOT: {
        JobState.AWAITING_QR,
        JobState.QR_READY,
        JobState.DONE,
        JobState.LOGGING_IN,
        JobState.RETRY_SCHEDULED,
        JobState.FAILED,
        JobState.STOPPED,
    },
    JobState.AWAITING_QR: {
        JobState.QR_READY,
        JobState.DONE,
        JobState.RETRY_SCHEDULED,
        JobState.FAILED,
        JobState.STALE,
        JobState.STOPPED,
    },
    JobState.QR_READY: {
        JobState.DONE,
        JobState.RETRY_SCHEDULED,
        JobState.FAILED,
        JobState.STALE,
        JobState.STOPPED,
    },
    JobState.RETRY_SCHEDULED: {
        JobState.SUBMITTING_BOT,
        JobState.QUEUED,
        JobState.HELD,
        JobState.STOPPED,
    },
}


class IllegalTransitionError(Exception):
    pass


class ActionNotAllowed(Exception):
    def __init__(self, action: str, state: JobState) -> None:
        self.action = action
        self.state = state
        super().__init__(f"action_not_allowed:{action}:{state.value}")


class JobNotFound(Exception):
    pass


def parse_bulk(raw_text: str) -> dict[str, Any]:
    lines = raw_text.splitlines()
    accounts: list[AccountRecord] = []
    invalid: list[dict[str, Any]] = []
    empty = 0
    seen: set[str] = set()
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            empty += 1
            continue
        parts = [p.strip() for p in stripped.split("|")]
        if len(parts) != 3:
            invalid.append({"line": i, "reason": "missing field (need email|pass|2fa)"})
            continue
        email, password, totp = parts
        email_n = email.lower()
        if not EMAIL_RE.match(email_n):
            invalid.append({"line": i, "reason": "invalid email format"})
            continue
        if not (1 <= len(password) <= 128):
            invalid.append({"line": i, "reason": "invalid password length (1-128)"})
            continue
        totp_clean = totp.replace(" ", "").upper()
        if not (16 <= len(totp_clean) <= 64) or not BASE32_RE.match(totp_clean):
            invalid.append({"line": i, "reason": "invalid 2fa format (Base32 16-64)"})
            continue
        if email_n in seen:
            invalid.append({"line": i, "reason": "duplicate email"})
            continue
        seen.add(email_n)
        accounts.append(
            AccountRecord(email=email_n, password=password, totp_secret=totp_clean)
        )
    return {
        "accounts": accounts,
        "invalid_lines": invalid,
        "empty_count": empty,
        "valid_count": len(accounts),
        "error_count": len(invalid),
    }


class JobManager:
    def __init__(
        self,
        config: ConfigStore,
        db: Database,
        sse: JobStream,
        session_cache: SessionCache,
        rust_bot: RustBotClient,
        telegram: TelegramNotifier,
        plus: PlusDetector,
        results: ResultWriter,
        blocklist: BlocklistService,
    ) -> None:
        self.config = config
        self.db = db
        self.sse = sse
        self.session_cache = session_cache
        self.rust_bot = rust_bot
        self.telegram = telegram
        self.plus = plus
        self.results = results
        self.blocklist = blocklist
        self.log = get_logger()

        self.jobs: dict[str, JobRecord] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self._sessions: dict[str, SessionEntry] = {}
        self._active_emails: set[str] = set()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._active_count = 0
        self._cond = asyncio.Condition()
        self._dispatcher_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._paused = False
        self._pause_held_ids: set[str] = set()
        self._submit_lock = asyncio.Lock()

    def _existing_emails(self) -> set[str]:
        return {j.email.lower() for j in self.jobs.values()}

    async def _remove_jobs_for_email(
        self, email: str, *, except_id: str | None = None
    ) -> int:
        """Xóa mọi job cùng email (trừ except_id). Dùng khi rerun để giữ đúng 1 job/email."""
        email_n = email.lower()
        removed = 0
        for jid, job in list(self.jobs.items()):
            if job.email.lower() != email_n:
                continue
            if except_id and jid == except_id:
                continue
            if job.state in ACTIVE_STATES:
                try:
                    await self.stop_job(jid)
                except Exception:
                    pass
            self.jobs.pop(jid, None)
            self._pause_held_ids.discard(jid)
            self._active_emails.discard(email_n)
            await self.db.delete_job(jid)
            await self.sse.publish({"type": "deleted", "job_id": jid})
            removed += 1
        return removed

    async def start(self) -> None:
        for j in await self.db.list_jobs():
            if j.state in ACTIVE_STATES or j.state == JobState.RETRY_SCHEDULED:
                j.state = JobState.STOPPED
                j.last_error = "restart_stopped"
                j.ended_at = time.time()
            self.jobs[j.job_id] = j
        self._dispatcher_task = asyncio.create_task(self._dispatcher())
        self._watchdog_task = asyncio.create_task(self._stale_watchdog())
        self.sse.set_snapshot(lambda: [j.public_dict() for j in self.jobs.values()])

    async def stop(self) -> None:
        self._stop.set()
        for t in list(self.tasks.values()):
            t.cancel()
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
        if self._watchdog_task:
            self._watchdog_task.cancel()

    def list_public(self) -> list[dict[str, Any]]:
        return [j.public_dict() for j in self.jobs.values()]

    def get(self, job_id: str) -> JobRecord:
        job = self.jobs.get(job_id)
        if not job:
            raise JobNotFound(job_id)
        return job

    async def _transition(
        self,
        job: JobRecord,
        new_state: JobState,
        *,
        last_error: str | None = None,
        note: str | None = None,
    ) -> None:
        old = job.state
        if old == new_state:
            job.last_progress_at = time.time()
            if last_error is not None:
                job.last_error = last_error
            await self.db.upsert_job(job)
            await self.sse.publish(job.public_dict())
            return
        allowed = VALID_TRANSITIONS.get(old, set())
        if new_state not in allowed:
            raise IllegalTransitionError(f"{old.value} -> {new_state.value}")
        job.state = new_state
        if last_error is not None:
            job.last_error = last_error
        now = time.time()
        job.last_progress_at = now
        job.timeline.append(TimelineEntry(state=new_state, at=now, note=note))
        if new_state in CONCLUDED_STATES:
            job.ended_at = now
        await self.db.upsert_job(job)
        await self.sse.publish(job.public_dict())
        self.log.info(
            f"transition {old.value}->{new_state.value}",
            extra={
                "job_id": job.job_id,
                "email": job.email,
                "state": new_state.value,
                "event": "transition",
                "error_code": last_error,
            },
        )

    async def submit(
        self,
        raw_text: str,
        dispatch_mode: str = "default",
        skip_cache: bool | None = None,
    ) -> dict[str, Any]:
        # Lock chống double-click / concurrent submit tạo nhiều job cùng email
        async with self._submit_lock:
            return await self._submit_locked(raw_text, dispatch_mode, skip_cache)

    async def _submit_locked(
        self,
        raw_text: str,
        dispatch_mode: str,
        skip_cache: bool | None,
    ) -> dict[str, Any]:
        parsed = parse_bulk(raw_text)
        accounts: list[AccountRecord] = parsed["accounts"]
        kept, skipped = await self.blocklist.filter_submit(accounts)
        cfg = self.config.get()
        mode = DispatchOverride(dispatch_mode) if dispatch_mode else DispatchOverride.DEFAULT
        if mode == DispatchOverride.IMMEDIATE:
            initial = JobState.QUEUED
        elif mode == DispatchOverride.HOLD:
            initial = JobState.HELD
        elif cfg.flow_mode == FlowMode.MANUAL:
            initial = JobState.HELD
        else:
            initial = JobState.QUEUED

        # Global pause: mọi job chờ chuyển sang hold, không dispatch
        if self._paused and initial == JobState.QUEUED:
            initial = JobState.HELD

        # 1 email = 1 job — bỏ qua email đã có job (kể cả done/failed)
        existing = self._existing_emails()
        unique_kept: list[AccountRecord] = []
        for a in kept:
            key = a.email.lower()
            if key in existing:
                skipped.append({"email": a.email, "reason": "duplicate_job"})
                continue
            existing.add(key)
            unique_kept.append(a)
        kept = unique_kept

        if skip_cache is True or cfg.skip_session_cache:
            for a in kept:
                try:
                    self.session_cache.delete(a.email)
                except Exception:
                    pass

        created: list[dict[str, Any]] = []
        now = time.time()
        for a in kept:
            job = JobRecord(
                job_id=uuid.uuid4().hex,
                email=a.email,
                password=a.password,
                totp_secret=a.totp_secret,
                state=initial,
                held_flag=initial == JobState.HELD,
                created_at=now,
                last_progress_at=now,
                timeline=[TimelineEntry(state=initial, at=now)],
            )
            self.jobs[job.job_id] = job
            if self._paused and job.state == JobState.HELD:
                self._pause_held_ids.add(job.job_id)
            await self.db.upsert_job(job)
            await self.sse.publish(job.public_dict())
            if initial == JobState.QUEUED:
                await self._queue.put(job.job_id)
            created.append(job.public_dict())

        return {
            "created": created,
            "invalid_lines": parsed["invalid_lines"],
            "skipped": skipped,
            "valid_count": len(created),
            "error_count": parsed["error_count"] + len(skipped),
            "duplicate_count": sum(1 for s in skipped if s.get("reason") == "duplicate_job"),
        }

    async def _dispatcher(self) -> None:
        while not self._stop.is_set():
            if self._paused:
                await asyncio.sleep(0.5)
                continue
            try:
                job_id = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            job = self.jobs.get(job_id)
            if not job or job.state != JobState.QUEUED:
                continue
            if self._paused:
                # Race: pause giữa dequeue → put lại / hold
                try:
                    await self._transition(job, JobState.HELD)
                    job.held_flag = True
                    self._pause_held_ids.add(job.job_id)
                    await self.db.upsert_job(job)
                except IllegalTransitionError:
                    pass
                continue
            async with self._cond:
                while self._active_count >= self.config.get().concurrency_limit:
                    if self._stop.is_set():
                        return
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        pass
                if job.state != JobState.QUEUED or self._paused:
                    if job.state == JobState.QUEUED:
                        await self._queue.put(job_id)
                    continue
                self._active_count += 1
            self.tasks[job_id] = asyncio.create_task(self._run_pipeline(job))

    async def _release_slot(self) -> None:
        async with self._cond:
            self._active_count = max(0, self._active_count - 1)
            self._cond.notify_all()

    async def _run_pipeline(self, job: JobRecord) -> None:
        cfg = self.config.get()
        job.started_at = time.time()
        try:
            await asyncio.wait_for(
                self._pipeline_body(job),
                timeout=cfg.hard_timeout_seconds,
            )
        except asyncio.TimeoutError:
            try:
                await self._transition(job, JobState.FAILED, last_error="hard_timeout")
            except IllegalTransitionError:
                job.state = JobState.FAILED
                job.last_error = "hard_timeout"
                job.ended_at = time.time()
                await self.db.upsert_job(job)
                await self.sse.publish(job.public_dict())
        except asyncio.CancelledError:
            if job.state not in CONCLUDED_STATES and job.state != JobState.STOPPED:
                job.state = JobState.STOPPED
                job.last_error = job.last_error or "user_stopped"
                job.ended_at = time.time()
                await self.db.upsert_job(job)
                await self.sse.publish(job.public_dict())
            raise
        except Exception as exc:
            log_unclassified(str(exc), exc, job_id=job.job_id, email=job.email)
            if job.state not in CONCLUDED_STATES:
                try:
                    await self._transition(
                        job, JobState.FAILED, last_error="unclassified"
                    )
                except Exception:
                    job.state = JobState.FAILED
                    job.last_error = "unclassified"
                    await self.db.upsert_job(job)
                    await self.sse.publish(job.public_dict())
        finally:
            self.tasks.pop(job.job_id, None)
            self._active_emails.discard(job.email)
            await self._release_slot()

    async def _pipeline_body(self, job: JobRecord) -> None:
        cfg = self.config.get()
        # Session
        entry = self.session_cache.read(job.email)
        reuse = bool(
            entry
            and entry.access_token
            and should_reuse(
                entry.expires_at,
                time.time(),
                cfg.session_cache_ttl_buffer_seconds,
            )
        )
        if reuse and entry:
            await self._transition(job, JobState.SESSION_READY)
            self._sessions[job.job_id] = entry
            self.session_cache.touch(job.email)
        else:
            await self._transition(job, JobState.LOGGING_IN)
            entry = await self._login_with_backoff(job)
            self._sessions[job.job_id] = entry
            await self._transition(job, JobState.SESSION_READY)

        # Bot submit loop (handles pipeline retries internally via state)
        while True:
            if job.state == JobState.STOPPED:
                return
            if job.email in self._active_emails:
                await asyncio.sleep(1)
                continue
            self._active_emails.add(job.email)
            try:
                await self._transition(job, JobState.SUBMITTING_BOT)
                result = await self._run_bot_and_poll(job, self._sessions[job.job_id])
            finally:
                self._active_emails.discard(job.email)

            if result == "done":
                # QR terminal — slot được nhả trong finally của _run_pipeline
                return
            if result == "retry":
                delay = getattr(job, "_retry_delay", 30)
                await asyncio.sleep(delay)
                if job.state == JobState.STOPPED:
                    return
                continue
            if result == "failed":
                return
            if result == "relogin":
                await self._transition(job, JobState.LOGGING_IN)
                entry = await self._login_with_backoff(job)
                self._sessions[job.job_id] = entry
                await self._transition(job, JobState.SESSION_READY)
                continue
            return

    async def _login_with_backoff(self, job: JobRecord) -> SessionEntry:
        cfg = self.config.get()
        backoffs = list(cfg.login_backoff_seconds) or [2, 5, 15]
        last: Exception | None = None
        for attempt in range(len(backoffs) + 1):
            job.attempt_login = attempt + 1
            await self.db.upsert_job(job)
            try:
                entry = await do_login(
                    job.to_account(),
                    session_cache=self.session_cache,
                    logger=self.log,
                )
                job.cookies_summary = [
                    {"name": k, "domain": ".chatgpt.com"} for k in entry.cookies
                ]
                return entry
            except LoginError as e:
                last = e
                code = e.code
                if code in (
                    "login_credentials_invalid",
                    "login_challenge_unsupported",
                ):
                    await self._transition(job, JobState.FAILED, last_error=code)
                    raise
                if attempt >= len(backoffs):
                    await self._transition(
                        job, JobState.FAILED, last_error="login_exhausted"
                    )
                    raise LoginError(code="login_exhausted") from e
                await asyncio.sleep(backoffs[attempt])
            except Exception as e:
                last = e
                if attempt >= len(backoffs):
                    await self._transition(
                        job, JobState.FAILED, last_error="login_exhausted"
                    )
                    raise
                await asyncio.sleep(backoffs[attempt])
        raise last or LoginError(code="login_exhausted")

    async def _run_bot_and_poll(self, job: JobRecord, entry: SessionEntry) -> str:
        """Returns: done|retry|failed|relogin — QR done là terminal, không poll Plus."""
        cfg = self.config.get()
        self.rust_bot.configure(cfg.rust_bot_base_url, cfg.rust_bot_token)
        final_event: list[BotEvent] = []

        async def on_event(evt: BotEvent) -> None:
            job.last_progress_at = time.time()
            if evt.type == BotEventType.QR_READY and evt.qr:
                job.qr = evt.qr
                if job.state == JobState.SUBMITTING_BOT:
                    await self._transition(job, JobState.AWAITING_QR)
                if job.state in (JobState.AWAITING_QR, JobState.SUBMITTING_BOT):
                    await self._transition(job, JobState.QR_READY)
                else:
                    await self.sse.publish(job.public_dict())
                await self.telegram.send_qr(job, evt.qr)
            elif evt.type in (
                BotEventType.DONE,
                BotEventType.FAILED,
                BotEventType.TIMEOUT,
                BotEventType.CANCELLED,
            ):
                if evt.type == BotEventType.DONE and evt.qr:
                    job.qr = evt.qr
                final_event.append(evt)

        if job.state == JobState.SUBMITTING_BOT:
            await self._transition(job, JobState.AWAITING_QR)

        await self.rust_bot.run_bot_job(entry.access_token, job.email, on_event)

        if not final_event:
            return await self._handle_soft(job, "sse_stalled")

        evt = final_event[-1]
        if evt.type == BotEventType.FAILED:
            code = evt.error_code or "failed"
            if code == "invalid_session":
                self.session_cache.mark_invalid(job.email)
                return "relogin"
            if code in HARD_ERRORS:
                await self._transition(job, JobState.FAILED, last_error=code)
                await self.blocklist.on_job_failed(job)
                await self.telegram.send_event(job, "failed")
                return "failed"
            return await self._handle_soft(job, code)
        if evt.type == BotEventType.TIMEOUT:
            return await self._handle_soft(job, "bot_timeout")
        if evt.type == BotEventType.CANCELLED:
            return await self._handle_soft(job, "bot_cancelled")

        # DONE từ UPI = job hoàn thành (có QR/link). Check Plus là task phụ.
        if evt.qr:
            job.qr = evt.qr
        has_deliverable = bool(job.qr and (job.qr.qr_png_base64 or job.qr.payment_link))
        if not has_deliverable:
            return await self._handle_soft(job, "qr_incomplete")

        if job.state in (JobState.SUBMITTING_BOT, JobState.AWAITING_QR):
            try:
                await self._transition(job, JobState.QR_READY)
            except IllegalTransitionError:
                pass
        if job.qr:
            await self.telegram.send_qr(job, job.qr)
        await self._transition(job, JobState.DONE)
        await self.results.write_result(job, "done")
        await self.telegram.send_event(job, "done")
        return "done"

    async def _handle_soft(self, job: JobRecord, code: str) -> str:
        cfg = self.config.get()
        delay = SOFT_ERROR_DELAYS.get(code, 30)
        if job.attempt_pipeline < cfg.pipeline_retry_limit:
            job.attempt_pipeline += 1
            job._retry_delay = delay  # type: ignore[attr-defined]
            await self._transition(job, JobState.RETRY_SCHEDULED, last_error=code)
            return "retry"
        await self._transition(job, JobState.FAILED, last_error=code)
        await self.blocklist.on_job_failed(job)
        await self.telegram.send_event(job, "failed")
        return "failed"

    async def _stale_watchdog(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(10)
            cfg = self.config.get()
            now = time.time()
            for job in list(self.jobs.values()):
                if job.state not in ACTIVE_STATES:
                    continue
                if now - job.last_progress_at > cfg.stale_threshold_seconds:
                    t = self.tasks.get(job.job_id)
                    if t:
                        t.cancel()
                    try:
                        await self._transition(
                            job, JobState.STALE, last_error="stale_no_progress"
                        )
                    except IllegalTransitionError:
                        job.state = JobState.STALE
                        job.last_error = "stale_no_progress"
                        job.ended_at = now
                        await self.db.upsert_job(job)
                        await self.sse.publish(job.public_dict())

    # ── Job actions ──────────────────────────────────────────────

    async def start_job(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if job.state != JobState.HELD:
            raise ActionNotAllowed("start", job.state)
        if self._paused:
            # Đang pause toàn cục — giữ hold, không start
            self._pause_held_ids.add(job.job_id)
            raise ActionNotAllowed("start", job.state)
        await self._transition(job, JobState.QUEUED)
        job.held_flag = False
        self._pause_held_ids.discard(job.job_id)
        await self._queue.put(job.job_id)
        self.log.info(
            "job_action start",
            extra={"job_id": job_id, "event": "audit", "email": job.email},
        )
        return job

    async def pause_dispatch(self) -> dict[str, Any]:
        """Pause: job đang chạy tiếp; job chờ (queued) → held cho đến khi resume."""
        self._paused = True
        held = 0
        for job in list(self.jobs.values()):
            if job.state == JobState.QUEUED:
                try:
                    await self._transition(job, JobState.HELD)
                    job.held_flag = True
                    self._pause_held_ids.add(job.job_id)
                    await self.db.upsert_job(job)
                    held += 1
                except IllegalTransitionError:
                    continue
        await self.sse.publish_bulk(
            {"action": "pause", "paused": True, "held": held}
        )
        self.log.info(
            "dispatch paused",
            extra={"event": "audit", "held": held},
        )
        return {"paused": True, "held": held}

    async def resume_dispatch(self) -> dict[str, Any]:
        """Resume: đưa các job bị hold bởi pause về queue."""
        self._paused = False
        started = 0
        for jid in list(self._pause_held_ids):
            job = self.jobs.get(jid)
            if not job or job.state != JobState.HELD:
                self._pause_held_ids.discard(jid)
                continue
            try:
                await self._transition(job, JobState.QUEUED)
                job.held_flag = False
                await self.db.upsert_job(job)
                await self._queue.put(job.job_id)
                self._pause_held_ids.discard(jid)
                started += 1
            except IllegalTransitionError:
                self._pause_held_ids.discard(jid)
                continue
        await self.sse.publish_bulk(
            {"action": "resume", "paused": False, "started": started}
        )
        self.log.info(
            "dispatch resumed",
            extra={"event": "audit", "started": started},
        )
        return {"paused": False, "started": started}

    def pause_status(self) -> dict[str, Any]:
        return {
            "paused": self._paused,
            "pause_held": len(self._pause_held_ids),
        }

    async def stop_job(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if job.state in CONCLUDED_STATES and job.state != JobState.HELD:
            if job.state == JobState.STOPPED:
                return job
        t = self.tasks.get(job_id)
        job.last_error = "user_stopped"
        if job.state == JobState.HELD or job.state == JobState.QUEUED or job.state == JobState.RETRY_SCHEDULED:
            await self._transition(job, JobState.STOPPED, last_error="user_stopped")
        elif job.state in ACTIVE_STATES:
            if t and not t.done():
                t.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(t), timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    pass
            if job.state != JobState.STOPPED:
                try:
                    await self._transition(
                        job, JobState.STOPPED, last_error="user_stopped"
                    )
                except IllegalTransitionError:
                    job.state = JobState.STOPPED
                    job.last_error = "user_stopped"
                    job.ended_at = time.time()
                    await self.db.upsert_job(job)
                    await self.sse.publish(job.public_dict())
        else:
            raise ActionNotAllowed("stop", job.state)
        return job

    async def rerun_job(self, job_id: str) -> dict[str, str]:
        job = self.get(job_id)
        if job.state not in RERUNNABLE_STATES:
            raise ActionNotAllowed("rerun", job.state)
        if not job.password or not job.totp_secret:
            raise ActionNotAllowed("rerun", job.state)
        # Không cho rerun nếu cùng email đang chạy job khác
        for other in self.jobs.values():
            if other.job_id == job.job_id:
                continue
            if other.email.lower() != job.email.lower():
                continue
            if other.state not in CONCLUDED_STATES:
                raise ActionNotAllowed("rerun", other.state)
        email = job.email
        password = job.password
        totp = job.totp_secret
        origin_id = job.job_id
        # Xóa job cũ cùng email → giữ đúng 1 job/email
        await self._remove_jobs_for_email(email)
        now = time.time()
        cfg = self.config.get()
        initial = JobState.QUEUED if cfg.flow_mode == FlowMode.AUTO else JobState.HELD
        if self._paused and initial == JobState.QUEUED:
            initial = JobState.HELD
        new = JobRecord(
            job_id=uuid.uuid4().hex,
            email=email,
            password=password,
            totp_secret=totp,
            state=initial,
            held_flag=initial == JobState.HELD,
            origin_job_id=origin_id,
            created_at=now,
            last_progress_at=now,
            timeline=[TimelineEntry(state=initial, at=now)],
        )
        self.jobs[new.job_id] = new
        if self._paused and new.state == JobState.HELD:
            self._pause_held_ids.add(new.job_id)
        await self.db.upsert_job(new)
        await self.sse.publish(new.public_dict())
        if initial == JobState.QUEUED:
            await self._queue.put(new.job_id)
        return {"new_job_id": new.job_id, "origin_job_id": origin_id}

    async def check_plan(self, job_id: str) -> dict[str, Any]:
        """Side task: không đổi state DONE, không chiếm worker slot."""
        job = self.get(job_id)
        if job.state not in CHECK_PLAN_STATES:
            raise ActionNotAllowed("check-plan", job.state)
        entry = self._sessions.get(job_id) or self.session_cache.read(job.email)
        if not entry:
            job.plan_result = "pending"
            await self.sse.publish(job.public_dict())
            return {
                "polled": False,
                "result": "pending",
                "state": job.state.value,
                "plan_result": job.plan_result,
            }
        result = await self.plus.check_plan(job, entry)
        job.plan_result = result
        note = f"check_plus={result}"
        job.timeline.append(
            TimelineEntry(state=job.state, at=time.time(), note=note)
        )
        if result == "plus":
            await self.results.write_result(job, "plus")
        await self.db.upsert_job(job)
        await self.sse.publish(job.public_dict())
        return {
            "polled": True,
            "result": result,
            "state": job.state.value,
            "plan_result": job.plan_result,
        }

    async def remove_job(self, job_id: str) -> None:
        job = self.get(job_id)
        if job.state in ACTIVE_STATES or job.state in (
            JobState.QUEUED,
            JobState.HELD,
            JobState.RETRY_SCHEDULED,
        ):
            try:
                await self.stop_job(job_id)
            except Exception:
                pass
        self.jobs.pop(job_id, None)
        await self.db.delete_job(job_id)
        await self.sse.publish({"type": "deleted", "job_id": job_id})

    def get_qr_png(self, job_id: str) -> bytes | None:
        job = self.get(job_id)
        if not job.qr or not job.qr.qr_png_base64:
            return None
        if time.time() - job.qr.received_at > 86400:
            return None
        try:
            return base64.b64decode(job.qr.qr_png_base64)
        except Exception:
            return None

    # ── Bulk ─────────────────────────────────────────────────────

    async def stop_all(self) -> dict[str, Any]:
        stopped = 0
        skipped = 0
        reasons: dict[str, int] = {}
        for job in list(self.jobs.values()):
            if job.state in ACTIVE_STATES or job.state in (
                JobState.QUEUED,
                JobState.HELD,
                JobState.RETRY_SCHEDULED,
            ):
                try:
                    await self.stop_job(job.job_id)
                    stopped += 1
                except Exception as e:
                    skipped += 1
                    reasons[str(e)] = reasons.get(str(e), 0) + 1
            else:
                skipped += 1
                reasons["not_active"] = reasons.get("not_active", 0) + 1
        await self.sse.publish_bulk(
            {"action": "stop_all", "stopped": stopped, "skipped": skipped}
        )
        return {"stopped": stopped, "skipped": skipped, "skipped_reasons": reasons}

    async def start_all_held(self) -> dict[str, int]:
        started = 0
        for job in list(self.jobs.values()):
            if job.state == JobState.HELD:
                await self.start_job(job.job_id)
                started += 1
        await self.sse.publish_bulk({"action": "start_all_held", "started": started})
        return {"started": started}

    async def rerun_failed(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for job in list(self.jobs.values()):
            if job.state in (JobState.FAILED, JobState.STALE, JobState.FREE_TIMEOUT):
                try:
                    out.append(await self.rerun_job(job.job_id))
                except ActionNotAllowed:
                    continue
        await self.sse.publish_bulk({"action": "rerun_failed", "count": len(out)})
        return out

    async def clear(self, filter_name: str, confirm: bool = False) -> dict[str, int]:
        if filter_name not in ("failed", "done", "all"):
            raise ValueError("invalid_filter")
        if filter_name == "all" and not confirm:
            raise PermissionError("confirm_required")
        to_delete: list[str] = []
        for jid, job in self.jobs.items():
            if filter_name == "failed" and job.state == JobState.FAILED:
                to_delete.append(jid)
            elif filter_name == "done" and job.state in (
                JobState.DONE,
                JobState.PLUS_CONFIRMED,
                JobState.FREE_TIMEOUT,
                JobState.STOPPED,
            ):
                to_delete.append(jid)
            elif filter_name == "all":
                to_delete.append(jid)
        for jid in to_delete:
            job = self.jobs.get(jid)
            if not job:
                continue
            if filter_name != "all" and job.state in ACTIVE_STATES | {
                JobState.HELD,
                JobState.QUEUED,
                JobState.RETRY_SCHEDULED,
            }:
                continue
            if filter_name == "all" and job.state in ACTIVE_STATES:
                try:
                    await self.stop_job(jid)
                except Exception:
                    pass
            self.jobs.pop(jid, None)
            await self.db.delete_job(jid)
        outputs: dict[str, int] = {}
        if filter_name == "all":
            # Clear all cũng xóa file Done / Plus (và free legacy)
            outputs = await self.results.clear_outputs(("done", "plus", "free"))
        await self.sse.publish_bulk(
            {
                "action": "clear",
                "filter": filter_name,
                "cleared": len(to_delete),
                "outputs": outputs,
            }
        )
        return {"cleared": len(to_delete), "outputs": outputs}
