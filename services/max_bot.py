from __future__ import annotations

import asyncio
import json
import ssl
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from config import (
    MAX_API_BASE_URL,
    MAX_BOT_TOKEN,
    MAX_REQUIRED_CHANNEL_ID,
    MAX_REQUIRED_CHANNEL_URL,
)


class MaxApiError(RuntimeError):
    pass


MAX_CA_BUNDLE = Path(__file__).resolve().parents[1] / "certs" / "russian_trusted_ca.pem"


@dataclass(frozen=True)
class SubscriptionStatus:
    required: bool
    subscribed: bool
    channel_url: str


class MaxBotClient:
    def __init__(self, token: str = MAX_BOT_TOKEN, base_url: str = MAX_API_BASE_URL):
        self.token = token
        self.base_url = base_url.rstrip("/")

    def _request_sync(self, method: str, path: str, *, query=None, payload=None) -> dict:
        if not self.token:
            raise MaxApiError("MAX_BOT_TOKEN is not configured")
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query, doseq=True)}"
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        request = Request(
            url,
            data=body,
            method=method,
            headers={
                "Authorization": self.token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            context = ssl.create_default_context()
            if urlsplit(self.base_url).hostname == "platform-api2.max.ru" and MAX_CA_BUNDLE.is_file():
                context.load_verify_locations(cafile=str(MAX_CA_BUNDLE))
            with urlopen(request, timeout=15, context=context) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise MaxApiError(f"MAX API returned {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise MaxApiError(f"MAX API is unavailable: {exc}") from exc
        return json.loads(raw) if raw else {}

    async def request(self, method: str, path: str, *, query=None, payload=None) -> dict:
        return await asyncio.to_thread(
            self._request_sync, method, path, query=query, payload=payload
        )

    async def is_channel_member(self, user_id: int) -> bool:
        if not MAX_REQUIRED_CHANNEL_ID:
            return True
        data = await self.request(
            "GET",
            f"/chats/{MAX_REQUIRED_CHANNEL_ID}/members",
            query={"user_ids": [int(user_id)]},
        )
        return any(int(item.get("user_id", 0)) == int(user_id) for item in data.get("members", []))

    async def subscription_status(self, user_id: int) -> SubscriptionStatus:
        required = bool(MAX_REQUIRED_CHANNEL_ID)
        return SubscriptionStatus(
            required=required,
            subscribed=(await self.is_channel_member(user_id)) if required else True,
            channel_url=MAX_REQUIRED_CHANNEL_URL,
        )


max_bot = MaxBotClient()
