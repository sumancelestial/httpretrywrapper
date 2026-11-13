import logging
from collections.abc import Callable
from typing import Any

import pytest
import requests

from httpclient import fetch_json, retry_with_backoff

URL = "https://example.com/data"


def _http_error(status_code: int) -> requests.exceptions.HTTPError:
    """Build an HTTPError carrying a response with the given status code."""
    response = requests.Response()
    response.status_code = status_code
    return requests.exceptions.HTTPError(f"{status_code} error", response=response)


def _scripted(
    errors: list[Exception], result: Any
) -> tuple[Callable[[], Any], list[Any]]:
    """Build a no-arg function raising each error in turn, then returning result.

    Returns (func, calls) where calls records the outcome of each invocation,
    so tests can assert exactly how many attempts were made.
    """
    calls: list[Any] = []

    def func() -> Any:
        outcome = errors[len(calls)] if len(calls) < len(errors) else result
        calls.append(outcome)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return func, calls


def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace time.sleep in httpclient with a recorder; return the delays."""
    sleeps: list[float] = []
    monkeypatch.setattr(
        "httpclient.time.sleep", lambda seconds: sleeps.append(seconds)
    )
    return sleeps


def test_fetch_json_success(requests_mock):
    requests_mock.get("https://example.com/data", json={"ok": True})
    result = fetch_json("https://example.com/data")
    assert result == {"ok": True}


def test_fetch_json_raises_on_error(requests_mock):
    requests_mock.get("https://example.com/data", status_code=500)
    try:
        fetch_json("https://example.com/data")
        assert False, "expected an exception"
    except Exception:
        pass


def test_retry_with_backoff_success_on_first_try(monkeypatch):
    sleeps = _no_sleep(monkeypatch)
    func, calls = _scripted([], {"ok": True})
    wrapped = retry_with_backoff()(func)

    assert wrapped() == {"ok": True}
    assert len(calls) == 1
    assert sleeps == []


def test_retry_with_backoff_retries_then_succeeds(monkeypatch, caplog):
    sleeps = _no_sleep(monkeypatch)
    func, calls = _scripted([_http_error(503)], {"ok": True})
    wrapped = retry_with_backoff()(func)

    with caplog.at_level(logging.WARNING, logger="httpclient"):
        assert wrapped() == {"ok": True}

    assert len(calls) == 2
    assert len(sleeps) == 1
    assert 0 <= sleeps[0] <= 0.5  # base delay with full jitter
    assert "retrying" in caplog.text


def test_retry_with_backoff_raises_after_exhaustion(monkeypatch):
    sleeps = _no_sleep(monkeypatch)
    func, calls = _scripted(
        [requests.exceptions.Timeout("timed out")] * 5, {"ok": True}
    )
    wrapped = retry_with_backoff(max_attempts=3)(func)

    with pytest.raises(requests.exceptions.Timeout):
        wrapped()

    assert len(calls) == 3
    assert len(sleeps) == 2
    assert 0 <= sleeps[0] <= 0.5
    assert 0 <= sleeps[1] <= 1.0  # backoff doubles on the second retry


def test_retry_with_backoff_fails_fast_on_non_retryable_error(monkeypatch):
    sleeps = _no_sleep(monkeypatch)
    func, calls = _scripted([_http_error(404)] * 5, {"ok": True})
    wrapped = retry_with_backoff()(func)

    with pytest.raises(requests.exceptions.HTTPError):
        wrapped()

    assert len(calls) == 1
    assert sleeps == []


def test_fetch_json_retries_transient_http_error(requests_mock, monkeypatch):
    sleeps = _no_sleep(monkeypatch)
    requests_mock.get(
        URL,
        [
            {"status_code": 503},
            {"json": {"ok": True}},
        ],
    )

    assert fetch_json(URL) == {"ok": True}
    assert requests_mock.call_count == 2
    assert len(sleeps) == 1
