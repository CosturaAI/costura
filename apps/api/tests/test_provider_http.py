"""Status handling shared by every provider client."""

import httpx
import pytest

from costura.providers.http import ProviderApiError, ProviderAuthError, request_json


def _call(*responses: httpx.Response) -> tuple[dict[str, object], list[float]]:
    queue = list(responses)
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0)

    with httpx.Client(base_url="https://api.example", transport=httpx.MockTransport(handler)) as c:
        payload = request_json(c, "GET", "/x", max_retries=2, sleep=sleeps.append, label="Example")
    return payload, sleeps


def test_a_rate_limited_403_is_retried_not_treated_as_a_rejected_key() -> None:
    payload, sleeps = _call(
        httpx.Response(403, headers={"x-ratelimit-remaining": "0"}),
        httpx.Response(403, headers={"retry-after": "3"}),
        httpx.Response(200, json={"ok": True}),
    )
    assert payload == {"ok": True}
    assert sleeps[1] == 3.0


def test_a_plain_403_is_still_an_auth_error() -> None:
    with pytest.raises(ProviderAuthError):
        _call(httpx.Response(403, json={"message": "Bad credentials"}))


def test_a_rate_limit_that_never_lifts_is_unavailable_not_auth() -> None:
    limited = httpx.Response(403, headers={"x-ratelimit-remaining": "0"})
    with pytest.raises(ProviderApiError) as raised:
        _call(limited, limited, limited)
    assert not isinstance(raised.value, ProviderAuthError)
    assert raised.value.unavailable


@pytest.mark.parametrize("value", ["-5", "nan", "inf", "soon"])
def test_a_retry_after_that_is_not_a_usable_wait_does_not_crash(value: str) -> None:
    payload, sleeps = _call(
        httpx.Response(429, headers={"retry-after": value}),
        httpx.Response(200, json={"ok": True}),
    )
    assert payload == {"ok": True}
    assert len(sleeps) == 1 and 0.0 <= sleeps[0] <= 30.0
