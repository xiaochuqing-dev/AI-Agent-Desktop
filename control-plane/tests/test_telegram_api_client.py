from __future__ import annotations

import asyncio
import json
import socket
import ssl

import httpx
import pytest

from control_plane.telegram.api_client import TelegramApiError, TelegramBotApiClient


def transport_for(payload: dict, *, status_code: int = 200):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=json.dumps(payload).encode(), request=request)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    ("error_code", "expected"),
    [
        (401, "TELEGRAM_UNAUTHORIZED"),
        (403, "TELEGRAM_FORBIDDEN"),
        (409, "TELEGRAM_UPDATE_CONFLICT"),
        (429, "TELEGRAM_RATE_LIMITED"),
    ],
)
def test_telegram_api_maps_protocol_errors(error_code, expected):
    payload = {
        "ok": False,
        "error_code": error_code,
        "description": "synthetic",
        "parameters": {"retry_after": 1},
    }
    client = TelegramBotApiClient(
        transport=transport_for(payload),
        max_rate_limit_retries=0,
    )
    with pytest.raises(TelegramApiError) as caught:
        asyncio.run(client.get_me("100001:synthetic"))
    assert caught.value.code == expected
    assert "100001:synthetic" not in str(caught.value)


def test_get_me_webhook_and_updates_success():
    async def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        results = {
            "getMe": {
                "id": 42,
                "is_bot": True,
                "username": "fake_bot",
                "first_name": "Fake",
            },
            "getWebhookInfo": {"url": "", "pending_update_count": 2},
            "getUpdates": [{"update_id": 9, "message": {"text": "ignored here"}}],
        }
        return httpx.Response(
            200,
            json={"ok": True, "result": results[method]},
            request=request,
        )

    client = TelegramBotApiClient(transport=httpx.MockTransport(handler))
    identity = asyncio.run(client.get_me("100001:synthetic"))
    webhook = asyncio.run(client.get_webhook_info("100001:synthetic"))
    updates = asyncio.run(client.get_updates("100001:synthetic", offset=9, timeout_seconds=0))
    assert identity["id"] == 42
    assert webhook.url_present is False
    assert webhook.pending_update_count == 2
    assert [item.update_id for item in updates] == [9]


class RaisingTransport(httpx.AsyncBaseTransport):
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        del request
        raise self.error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ReadTimeout("synthetic timeout"), "TELEGRAM_TIMEOUT"),
        (socket.gaierror("synthetic dns"), "TELEGRAM_DNS_ERROR"),
        (ssl.SSLError("synthetic tls"), "TELEGRAM_TLS_ERROR"),
    ],
)
def test_telegram_api_maps_transport_errors(error, expected):
    client = TelegramBotApiClient(transport=RaisingTransport(error))
    with pytest.raises(TelegramApiError) as caught:
        asyncio.run(client.get_me("100001:synthetic"))
    assert caught.value.code == expected


def test_webhook_delete_requires_explicit_confirmation():
    client = TelegramBotApiClient(transport=transport_for({"ok": True, "result": True}))
    with pytest.raises(TelegramApiError) as caught:
        asyncio.run(
            client.delete_webhook(
                "100001:synthetic",
                explicit_confirmation=False,
            )
        )
    assert caught.value.code == "TELEGRAM_DELETE_WEBHOOK_CONFIRMATION_REQUIRED"


def test_cancel_event_interrupts_long_poll():
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json={"ok": True, "result": []}, request=request)

    async def run() -> None:
        event = asyncio.Event()
        event.set()
        client = TelegramBotApiClient(transport=httpx.MockTransport(handler))
        with pytest.raises(TelegramApiError) as caught:
            await client.get_updates(
                "100001:synthetic",
                offset=0,
                timeout_seconds=5,
                cancel_event=event,
            )
        assert caught.value.code == "TELEGRAM_REQUEST_CANCELED"

    asyncio.run(run())
