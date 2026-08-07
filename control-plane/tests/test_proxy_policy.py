from __future__ import annotations

import asyncio

import httpx
import pytest

from control_plane.network.proxy import ProxyPolicy, ProxyPolicyError
from control_plane.telegram.api_client import TelegramApiError, TelegramBotApiClient


def test_direct_policy_does_not_read_environment():
    policy = ProxyPolicy(
        mode="direct",
        environment={"HTTPS_PROXY": "http://should-not-be-used.invalid:8080"},
    )
    url, state = policy.resolve()
    assert url is None
    assert state.mode == "direct"
    assert state.source == "none"
    assert state.status == "ready"


def test_environment_and_explicit_proxy_are_visible_without_secrets():
    environment = ProxyPolicy(
        mode="environment",
        environment={"HTTPS_PROXY": "http://127.0.0.1:8080"},
    )
    url, state = environment.resolve()
    assert url == "http://127.0.0.1:8080"
    assert state.effective_proxy == "http://127.0.0.1:8080"

    secret = "proxy password/with spaces"
    explicit = ProxyPolicy(
        mode="explicit",
        explicit_url="http://proxy-user@127.0.0.1:8081",
        credential_reference_id="proxy/telegram",
    )
    resolved, visible = explicit.resolve(secret_resolver=lambda _reference: secret)
    assert resolved is not None and "proxy-user:" in resolved
    assert secret not in resolved
    assert visible.effective_proxy == "http://127.0.0.1:8081"
    assert secret not in repr(explicit)
    assert secret not in visible.model_dump_json()


@pytest.mark.parametrize(
    "value",
    [
        "http://user:password@127.0.0.1:8080",
        "http://user@127.0.0.1:8080",
    ],
)
def test_inline_proxy_authentication_is_rejected(value):
    policy = ProxyPolicy(mode="explicit", explicit_url=value)
    with pytest.raises(ProxyPolicyError) as caught:
        policy.resolve()
    assert caught.value.code == "TELEGRAM_PROXY_INLINE_CREDENTIAL_FORBIDDEN"
    assert "password" not in str(caught.value)
    assert "password" not in repr(policy)


def test_proxy_credential_requires_resolver():
    policy = ProxyPolicy(
        mode="explicit",
        explicit_url="http://127.0.0.1:8080",
        credential_reference_id="proxy/telegram",
    )
    with pytest.raises(ProxyPolicyError) as caught:
        policy.resolve()
    assert caught.value.code == "TELEGRAM_PROXY_CREDENTIAL_UNAVAILABLE"
    state = policy.state()
    assert state.status == "invalid"
    assert state.effective_proxy is None


def test_send_message_does_not_retry_rate_limit_or_timeout():
    calls = 0

    async def rate_limited(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "ok": False,
                "error_code": 429,
                "parameters": {"retry_after": 1},
            },
            request=request,
        )

    client = TelegramBotApiClient(
        transport=httpx.MockTransport(rate_limited),
        max_rate_limit_retries=5,
    )
    with pytest.raises(TelegramApiError) as caught:
        asyncio.run(client.send_message("100001:synthetic", chat_id=42, text="acceptance"))
    assert caught.value.code == "TELEGRAM_RATE_LIMITED"
    assert calls == 1


def test_proxy_authentication_failure_is_stable_and_secret_free():
    async def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(407, json={}, request=request)

    client = TelegramBotApiClient(transport=httpx.MockTransport(rejected))
    with pytest.raises(TelegramApiError) as caught:
        asyncio.run(client.get_me("100001:synthetic"))
    assert caught.value.code == "TELEGRAM_PROXY_AUTHENTICATION_FAILED"
    assert "100001:synthetic" not in str(caught.value)
