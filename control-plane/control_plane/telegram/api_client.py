from __future__ import annotations

import asyncio
import json
import socket
import ssl
from dataclasses import dataclass
from typing import Any

import httpx

from .models import TelegramUpdate, TelegramWebhookInfo


@dataclass(frozen=True)
class TelegramApiError(Exception):
    code: str
    message: str
    retryable: bool = False
    retry_after: int | None = None

    def __str__(self) -> str:
        return self.message


class TelegramBotApiClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.telegram.org",
        transport: httpx.AsyncBaseTransport | None = None,
        response_limit_bytes: int = 1024 * 1024,
        connect_timeout_seconds: float = 10.0,
        max_rate_limit_retries: int = 1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.response_limit_bytes = response_limit_bytes
        self.connect_timeout_seconds = connect_timeout_seconds
        self.max_rate_limit_retries = max_rate_limit_retries

    async def get_me(
        self, token: str, *, cancel_event: asyncio.Event | None = None
    ) -> dict[str, Any]:
        result = await self._call("getMe", token, {}, timeout_seconds=10, cancel_event=cancel_event)
        if not isinstance(result, dict):
            raise TelegramApiError(
                "TELEGRAM_RESPONSE_INVALID", "Telegram getMe returned an invalid response."
            )
        return result

    async def get_webhook_info(
        self, token: str, *, cancel_event: asyncio.Event | None = None
    ) -> TelegramWebhookInfo:
        result = await self._call(
            "getWebhookInfo", token, {}, timeout_seconds=10, cancel_event=cancel_event
        )
        if not isinstance(result, dict):
            raise TelegramApiError(
                "TELEGRAM_RESPONSE_INVALID", "Telegram getWebhookInfo returned an invalid response."
            )
        return TelegramWebhookInfo(
            url_present=bool(result.get("url")),
            has_custom_certificate=bool(result.get("has_custom_certificate", False)),
            pending_update_count=max(0, int(result.get("pending_update_count", 0) or 0)),
            last_error_date=(
                int(result["last_error_date"]) if result.get("last_error_date") else None
            ),
            last_error_message_present=bool(result.get("last_error_message")),
            max_connections=(
                int(result["max_connections"]) if result.get("max_connections") else None
            ),
            allowed_updates=[str(item) for item in result.get("allowed_updates", [])],
        )

    async def get_updates(
        self,
        token: str,
        *,
        offset: int,
        timeout_seconds: int,
        cancel_event: asyncio.Event | None = None,
    ) -> list[TelegramUpdate]:
        result = await self._call(
            "getUpdates",
            token,
            {
                "offset": offset,
                "timeout": timeout_seconds,
                "allowed_updates": ["message"],
            },
            timeout_seconds=max(10, timeout_seconds + 5),
            cancel_event=cancel_event,
        )
        if not isinstance(result, list):
            raise TelegramApiError(
                "TELEGRAM_RESPONSE_INVALID", "Telegram getUpdates returned an invalid response."
            )
        updates: list[TelegramUpdate] = []
        for item in result:
            if not isinstance(item, dict) or not isinstance(item.get("update_id"), int):
                continue
            updates.append(TelegramUpdate(update_id=item["update_id"], payload=item))
        return updates

    async def delete_webhook(
        self,
        token: str,
        *,
        explicit_confirmation: bool,
        drop_pending_updates: bool = False,
        cancel_event: asyncio.Event | None = None,
    ) -> bool:
        if not explicit_confirmation:
            raise TelegramApiError(
                "TELEGRAM_DELETE_WEBHOOK_CONFIRMATION_REQUIRED",
                "Webhook deletion requires explicit confirmation.",
            )
        result = await self._call(
            "deleteWebhook",
            token,
            {"drop_pending_updates": drop_pending_updates},
            timeout_seconds=10,
            cancel_event=cancel_event,
        )
        return bool(result)

    async def _call(
        self,
        method: str,
        token: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
        cancel_event: asyncio.Event | None,
    ) -> Any:
        if not token:
            raise TelegramApiError("TELEGRAM_CREDENTIAL_MISSING", "Telegram credential is missing.")
        url = f"{self.base_url}/bot{token}/{method}"
        for attempt in range(self.max_rate_limit_retries + 1):
            try:
                response_payload = await self._request_json(
                    url, payload, timeout_seconds=timeout_seconds, cancel_event=cancel_event
                )
            except TelegramApiError:
                raise
            if bool(response_payload.get("ok")):
                return response_payload.get("result")
            error_code = int(response_payload.get("error_code", 0) or 0)
            parameters = response_payload.get("parameters") or {}
            retry_after = int(parameters.get("retry_after", 0) or 0) or None
            if (
                error_code == 429
                and retry_after is not None
                and attempt < self.max_rate_limit_retries
            ):
                await self._cancelable_sleep(min(retry_after, 30), cancel_event)
                continue
            if error_code == 401:
                raise TelegramApiError(
                    "TELEGRAM_UNAUTHORIZED", "Telegram rejected the bot credential.", False
                )
            if error_code == 403:
                raise TelegramApiError(
                    "TELEGRAM_FORBIDDEN", "Telegram denied the requested bot operation.", False
                )
            if error_code == 409:
                raise TelegramApiError(
                    "TELEGRAM_UPDATE_CONFLICT",
                    "Telegram reports another update consumer or an active webhook.",
                    True,
                )
            if error_code == 429:
                raise TelegramApiError(
                    "TELEGRAM_RATE_LIMITED",
                    "Telegram rate limited the request.",
                    True,
                    retry_after,
                )
            raise TelegramApiError(
                "TELEGRAM_API_ERROR", "Telegram returned an unsuccessful response.", True
            )
        raise TelegramApiError("TELEGRAM_API_ERROR", "Telegram request failed.", True)

    async def _request_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
        cancel_event: asyncio.Event | None,
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(
            connect=self.connect_timeout_seconds,
            read=timeout_seconds,
            write=10.0,
            pool=10.0,
        )
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                request_task = asyncio.create_task(client.post(url, json=payload))
                if cancel_event is None:
                    response = await request_task
                else:
                    cancel_task = asyncio.create_task(cancel_event.wait())
                    done, _pending = await asyncio.wait(
                        {request_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if cancel_task in done and cancel_event.is_set():
                        request_task.cancel()
                        await asyncio.gather(request_task, return_exceptions=True)
                        raise TelegramApiError(
                            "TELEGRAM_REQUEST_CANCELED", "Telegram request was canceled.", True
                        )
                    cancel_task.cancel()
                    response = await request_task
        except TelegramApiError:
            raise
        except httpx.TimeoutException:
            raise TelegramApiError(
                "TELEGRAM_TIMEOUT", "Telegram request timed out.", True
            ) from None
        except ssl.SSLError:
            raise TelegramApiError(
                "TELEGRAM_TLS_ERROR", "Telegram TLS connection failed.", True
            ) from None
        except socket.gaierror:
            raise TelegramApiError(
                "TELEGRAM_DNS_ERROR", "Telegram DNS resolution failed.", True
            ) from None
        except httpx.ConnectError as exc:
            causes: list[BaseException] = []
            cause: BaseException | None = exc
            while cause is not None and cause not in causes:
                causes.append(cause)
                cause = cause.__cause__ or cause.__context__
            if any(isinstance(item, ssl.SSLError) for item in causes):
                code = "TELEGRAM_TLS_ERROR"
                message = "Telegram TLS connection failed."
            elif any(isinstance(item, socket.gaierror) for item in causes):
                code = "TELEGRAM_DNS_ERROR"
                message = "Telegram DNS resolution failed."
            else:
                code = "TELEGRAM_NETWORK_ERROR"
                message = "Telegram network connection failed."
            raise TelegramApiError(code, message, True) from None
        except httpx.HTTPError:
            raise TelegramApiError(
                "TELEGRAM_NETWORK_ERROR", "Telegram network request failed.", True
            ) from None

        if len(response.content) > self.response_limit_bytes:
            raise TelegramApiError(
                "TELEGRAM_RESPONSE_TOO_LARGE", "Telegram response exceeded the safety limit."
            )
        try:
            parsed = json.loads(response.content)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TelegramApiError(
                "TELEGRAM_RESPONSE_INVALID", "Telegram returned invalid JSON."
            ) from None
        if not isinstance(parsed, dict):
            raise TelegramApiError(
                "TELEGRAM_RESPONSE_INVALID", "Telegram returned an invalid response object."
            )
        return parsed

    @staticmethod
    async def _cancelable_sleep(seconds: int, cancel_event: asyncio.Event | None) -> None:
        if cancel_event is None:
            await asyncio.sleep(seconds)
            return
        try:
            await asyncio.wait_for(cancel_event.wait(), timeout=seconds)
        except TimeoutError:
            return
        raise TelegramApiError("TELEGRAM_REQUEST_CANCELED", "Telegram request was canceled.", True)
