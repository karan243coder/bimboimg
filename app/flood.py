"""FloodWait protection — Telegram ban se bachao.

Telegram limits (official):
  • 30 messages/second global (bot-wide)
  • 1 message/second per chat  (burst 20 allowed, phir throttle)
  • 20 messages/minute per group
  • Limit todo -> TelegramRetryAfter, baar-baar todo -> temporary ban

Ye module 4 layer deta hai:
  1. GLOBAL token bucket   — 25 msg/s (30 se neeche, safety margin)
  2. PER-CHAT limiter      — 1 msg/s
  3. AUTO-RETRY            — TelegramRetryAfter par exact wait, phir retry
  4. ANTI-SPAM middleware  — user ki taraf se flood ho to drop
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.exceptions import (TelegramRetryAfter, TelegramForbiddenError,
                                TelegramBadRequest, TelegramNetworkError)
from aiogram.types import TelegramObject, Message, CallbackQuery

log = logging.getLogger("flood")

# ---------------------------------------------------------------- limits
GLOBAL_RPS = 20.0          # Telegram 30/s deta hai — 20 par rukte hain (safe margin)
PER_CHAT_INTERVAL = 1.05   # 1 msg/sec per chat (thoda margin)
MAX_RETRIES = 5


class TokenBucket:
    """Global rate limiter — poore bot ke liye."""

    def __init__(self, rate: float, capacity: float = None):
        self.rate = rate
        # burst capacity chhoti rakho: bhara hua bucket = instant burst,
        # jo Telegram ke 30/s ko todd sakta hai. 5 tokens = safe headroom.
        self.capacity = capacity if capacity is not None else min(5.0, rate)
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def take(self, n: float = 1.0):
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity,
                                  self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= n:
                    self.tokens -= n
                    return
                wait = (n - self.tokens) / self.rate
                await asyncio.sleep(min(wait, 1.0))


_global_bucket = TokenBucket(GLOBAL_RPS, capacity=5.0)
_chat_next: Dict[int, float] = defaultdict(float)
_chat_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

# stats
STATS = {"sent": 0, "retried": 0, "flood_waits": 0, "dropped": 0,
         "total_wait_s": 0.0, "blocked_users": 0}


async def _pace(chat_id: int):
    """Global + per-chat pacing."""
    await _global_bucket.take()
    async with _chat_locks[chat_id]:
        now = time.monotonic()
        nxt = _chat_next[chat_id]
        if now < nxt:
            await asyncio.sleep(nxt - now)
        _chat_next[chat_id] = max(now, nxt) + PER_CHAT_INTERVAL
    # purane chats saaf karo (memory leak na ho)
    if len(_chat_next) > 5000:
        cut = time.monotonic() - 300
        for k in [k for k, v in _chat_next.items() if v < cut][:2000]:
            _chat_next.pop(k, None)
            _chat_locks.pop(k, None)


async def safe_call(coro_factory: Callable[[], Awaitable], chat_id: int = 0,
                    what: str = "api"):
    """Koi bhi Telegram API call — paced + auto-retry on FloodWait.

    coro_factory: har retry par NAYA coroutine banata hai (coroutine reuse
                  nahi kar sakte, isliye lambda pass karo).
    """
    for attempt in range(MAX_RETRIES):
        try:
            if chat_id:
                await _pace(chat_id)
            else:
                await _global_bucket.take()
            res = await coro_factory()
            STATS["sent"] += 1
            return res

        except TelegramRetryAfter as e:
            wait = float(e.retry_after) + 0.5
            STATS["flood_waits"] += 1
            STATS["total_wait_s"] += wait
            STATS["retried"] += 1
            log.warning("FloodWait %ss on %s (attempt %d/%d) — waiting",
                        e.retry_after, what, attempt + 1, MAX_RETRIES)
            # us chat ko bhi peeche dhakelo
            if chat_id:
                _chat_next[chat_id] = time.monotonic() + wait
            await asyncio.sleep(wait)
            continue

        except TelegramForbiddenError:
            # user ne bot block kiya — retry bekaar
            STATS["blocked_users"] += 1
            log.info("user blocked bot (chat %s)", chat_id)
            return None

        except TelegramBadRequest as e:
            msg = str(e).lower()
            if "message is not modified" in msg or "message to delete" in msg:
                return None                      # harmless
            log.warning("bad request on %s: %s", what, e)
            return None

        except TelegramNetworkError as e:
            back = 1.5 ** attempt
            log.warning("network error on %s: %s — retry in %.1fs", what, e, back)
            await asyncio.sleep(back)
            continue

        except Exception as e:
            log.exception("unexpected on %s: %s", what, e)
            return None

    log.error("gave up on %s after %d retries", what, MAX_RETRIES)
    STATS["dropped"] += 1
    return None


# ---------------------------------------------------------------- middleware
class AntiFloodMiddleware(BaseMiddleware):
    """Incoming side — user spam kare to handler chalao hi mat.

    Ye zaroori hai: har incoming message par hum reply karte hain, to
    user ka flood = hamara flood = Telegram ban.
    """

    def __init__(self, per_sec: float = 0.7, burst: int = 5,
                 cooldown: int = 20):
        self.per_sec = per_sec
        self.burst = burst
        self.cooldown = cooldown
        self.hits: Dict[int, deque] = defaultdict(lambda: deque(maxlen=burst * 3))
        self.warned: Dict[int, float] = {}
        self.blocked: Dict[int, float] = {}
        super().__init__()

    async def __call__(self, handler, event: TelegramObject, data: Dict[str, Any]):
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)
        uid = user.id
        now = time.monotonic()

        # cooldown me hai?
        until = self.blocked.get(uid, 0)
        if now < until:
            STATS["dropped"] += 1
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer(f"⏳ {int(until - now)}s ruko", show_alert=False)
                except Exception:
                    pass
            return None

        h = self.hits[uid]
        while h and now - h[0] > 1.0 / self.per_sec * self.burst:
            h.popleft()
        h.append(now)

        if len(h) > self.burst:
            self.blocked[uid] = now + self.cooldown
            h.clear()
            log.info("user %s throttled for %ss", uid, self.cooldown)
            # ek hi baar warn karo (warna wo bhi flood hai)
            if now - self.warned.get(uid, 0) > 60:
                self.warned[uid] = now
                try:
                    if isinstance(event, Message):
                        await safe_call(
                            lambda: event.answer(
                                f"⏳ Bahut tez! {self.cooldown} second ruko."),
                            event.chat.id, "throttle-warn")
                    elif isinstance(event, CallbackQuery):
                        await event.answer(f"⏳ {self.cooldown}s ruko", show_alert=True)
                except Exception:
                    pass
            return None

        # memory cleanup
        if len(self.hits) > 5000:
            old = [k for k, v in self.hits.items() if not v or now - v[-1] > 300]
            for k in old[:2000]:
                self.hits.pop(k, None)
                self.blocked.pop(k, None)
                self.warned.pop(k, None)

        return await handler(event, data)


def stats() -> dict:
    return dict(STATS, chats_tracked=len(_chat_next))
