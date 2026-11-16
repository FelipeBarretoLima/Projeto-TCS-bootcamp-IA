"""Per-user usage limit (in memory): protects Gemini and statement processing from repeated
clicks or scripts. Each API process has its own count; it restarts along with it."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Annotated

from fastapi import Depends, HTTPException

from .auth import User, current_user


class RateLimit:
    def __init__(self, max_uses: int, window_seconds: float, action: str):
        self.max_uses, self.window, self.action = max_uses, window_seconds, action
        self._uses: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        """Counts one use; 429 if the key already used the maximum within the window."""
        now = time.monotonic()
        with self._lock:
            uses = self._uses[key]
            while uses and uses[0] <= now - self.window:
                uses.popleft()
            if len(uses) >= self.max_uses:
                wait = int(uses[0] + self.window - now) + 1
                raise HTTPException(429, f"muitas {self.action} seguidas: espere {wait} s e tente de novo")
            uses.append(now)

    def reset(self) -> None:
        with self._lock:
            self._uses.clear()


CHAT_LIMIT = RateLimit(10, 60, "perguntas")  # 10 questions per minute
IMPORT_LIMIT = RateLimit(20, 600, "importações")  # 20 statements every 10 minutes
# separate from the chat: a voice question spends one transcription + one question, without sharing the limit
TRANSCRIPTION_LIMIT = RateLimit(10, 60, "mensagens de voz")  # 10 per minute


def limit_chat(user: Annotated[User, Depends(current_user)]) -> None:
    CHAT_LIMIT.check(str(user.id))


def limit_import(user: Annotated[User, Depends(current_user)]) -> None:
    IMPORT_LIMIT.check(str(user.id))


def limit_transcription(user: Annotated[User, Depends(current_user)]) -> None:
    TRANSCRIPTION_LIMIT.check(str(user.id))
