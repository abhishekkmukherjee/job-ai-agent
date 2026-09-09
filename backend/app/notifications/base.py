from __future__ import annotations

from abc import ABC, abstractmethod


class NotificationError(Exception):
    pass


class NotificationProvider(ABC):
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    async def send(self, subject: str, body: str) -> None: ...
