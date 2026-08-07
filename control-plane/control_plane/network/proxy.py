from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import quote, urlsplit, urlunsplit

from ..observability.models import ProxyPolicyState

ProxyMode = Literal["direct", "environment", "explicit"]


class ProxyPolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProxyPolicy:
    """Explicit Telegram network policy.

    Environment mode reads only the standard proxy variables at call time. It never
    asks a library to discover arbitrary registry/PAC settings and never mutates the
    process or Windows proxy configuration.
    """

    mode: ProxyMode = "direct"
    explicit_url: str | None = field(default=None, repr=False)
    credential_reference_id: str | None = None
    environment: dict[str, str] | None = field(default=None, repr=False)

    def resolve(
        self,
        *,
        secret_resolver: Callable[[str], str] | None = None,
    ) -> tuple[str | None, ProxyPolicyState]:
        if self.mode == "direct":
            return None, ProxyPolicyState(
                mode="direct", source="none", effective_proxy=None, status="ready"
            )
        if self.mode == "environment":
            env = self.environment if self.environment is not None else os.environ
            value = (
                env.get("HTTPS_PROXY")
                or env.get("https_proxy")
                or env.get("HTTP_PROXY")
                or env.get("http_proxy")
            )
            if not value:
                return None, ProxyPolicyState(
                    mode="environment",
                    source="environment",
                    effective_proxy=None,
                    status="missing",
                    diagnostic_code="TELEGRAM_PROXY_NOT_CONFIGURED",
                )
            proxy = self._normalize(value, secret_resolver)
            return proxy, ProxyPolicyState(
                mode="environment",
                source="environment",
                effective_proxy=self._display(proxy),
                credential_reference_id=self.credential_reference_id,
                status="ready",
            )
        if self.mode != "explicit" or not self.explicit_url:
            raise ProxyPolicyError(
                "TELEGRAM_PROXY_INVALID", "Explicit proxy mode requires a proxy URL."
            )
        proxy = self._normalize(self.explicit_url, secret_resolver)
        return proxy, ProxyPolicyState(
            mode="explicit",
            source="explicit",
            effective_proxy=self._display(proxy),
            credential_reference_id=self.credential_reference_id,
            status="ready",
        )

    def state(self, *, secret_resolver: Callable[[str], str] | None = None) -> ProxyPolicyState:
        try:
            _proxy, state = self.resolve(secret_resolver=secret_resolver)
            return state
        except ProxyPolicyError as exc:
            return ProxyPolicyState(
                mode=self.mode,
                source="explicit" if self.mode == "explicit" else "environment",
                effective_proxy=None,
                credential_reference_id=self.credential_reference_id,
                status="invalid",
                diagnostic_code=exc.code,
            )

    def _normalize(self, value: str, secret_resolver: Callable[[str], str] | None) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https", "socks5", "socks5h"} or not parsed.hostname:
            raise ProxyPolicyError("TELEGRAM_PROXY_INVALID", "Proxy URL scheme or host is invalid.")
        if parsed.password is not None or (parsed.username and not self.credential_reference_id):
            raise ProxyPolicyError(
                "TELEGRAM_PROXY_INLINE_CREDENTIAL_FORBIDDEN",
                "Proxy authentication must use a CredentialRef, not an inline credential.",
            )
        if self.credential_reference_id:
            if secret_resolver is None:
                raise ProxyPolicyError(
                    "TELEGRAM_PROXY_CREDENTIAL_UNAVAILABLE",
                    "Proxy authentication requires a CredentialRef resolver.",
                )
            secret = secret_resolver(self.credential_reference_id)
            if not secret:
                raise ProxyPolicyError(
                    "TELEGRAM_PROXY_CREDENTIAL_UNAVAILABLE",
                    "Proxy authentication credential is unavailable.",
                )
            username = parsed.username or "proxy"
            netloc = f"{quote(username, safe='')}:{quote(secret, safe='')}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            parsed = parsed._replace(netloc=netloc)
        return urlunsplit(parsed)

    @staticmethod
    def _display(value: str) -> str:
        parsed = urlsplit(value)
        if parsed.hostname is None:
            return "<redacted>"
        netloc = parsed.hostname
        if parsed.port:
            netloc += f":{parsed.port}"
        return urlunsplit(parsed._replace(netloc=netloc, query="", fragment=""))
