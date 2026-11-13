import logging

import pytest
import requests

import httpclient
from httpclient import _backoff_delay, fetch_json, retry_with_backoff

URL = "https://example.com/data"

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

@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record sleeps instead of sleeping; make jitter deterministic (upper bound)."""
    sleeps: list[float] = []
    monkeypatch.setattr(httpclient.time, "sleep", sleeps.append)
    monkeypatch.setattr(httpclient.random, "uniform", lambda low, high: high)
    return sleeps

# --- fetch_json retry behavior -------------------------------------------

def test_fetch_json_succeeds_first_try(requests_mock, no_sleep):
    requests_mock.get(URL, json={"ok": True})
    assert fetch_json(URL) == {"ok": True}
    assert requests_mock.call_count == 1
    assert no_sleep == []

def test_fetch_json_succeeds_after_retries(requests_mock, no_sleep, caplog):
    requests_mock.get(URL, [
        {"status_code": 503},
        {"status_code": 429},
        {"status_code": 200, "json": {"ok": True}},
    ])
    with caplog.at_level(logging.WARNING, logger="httpclient"):
        assert fetch_json(URL) == {"ok": True}

    assert requests_mock.call_count == 3
    assert no_sleep == [0.5, 1.0]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert "attempt 1/3" in warnings[0]
    assert "HTTP 503" in warnings[0]
    assert "0.50s" in warnings[0]
    assert "attempt 2/3" in warnings[1]
    assert "HTTP 429" in warnings[1]
    assert "1.00s" in warnings[1]

def test_fetch_json_raises_after_max_attempts(requests_mock, no_sleep, caplog):
    requests_mock.get(URL, [{"status_code": 504}] * 3)
    with (
        caplog.at_level(logging.WARNING, logger="httpclient"),
        pytest.raises(requests.HTTPError),
    ):
        fetch_json(URL)

    assert requests_mock.call_count == 3
    assert len(no_sleep) == 2
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "giving up after 3 attempts" in errors[0]
    assert "HTTP 504" in errors[0]

def test_fetch_json_fails_fast_on_non_retryable(requests_mock, no_sleep, caplog):
    requests_mock.get(URL, status_code=404)
    with (
        caplog.at_level(logging.WARNING, logger="httpclient"),
        pytest.raises(requests.HTTPError),
    ):
        fetch_json(URL)

    assert requests_mock.call_count == 1
    assert no_sleep == []
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "non-retryable" in errors[0]
    assert "HTTP 404" in errors[0]

# --- retry_with_backoff in isolation (no HTTP) ---------------------------

def test_retry_with_backoff_retries_timeouts(no_sleep):
    calls = []

    @retry_with_backoff(max_attempts=3, base_delay=0.1)
    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise requests.ReadTimeout("slow")
        return "done"

    assert flaky() == "done"
    assert len(calls) == 3
    assert no_sleep == [0.1, 0.2]

def test_retry_with_backoff_single_attempt_does_not_retry(no_sleep):
    calls = []

    @retry_with_backoff(max_attempts=1)
    def always_times_out() -> None:
        calls.append(1)
        raise requests.Timeout("slow")

    with pytest.raises(requests.Timeout):
        always_times_out()
    assert len(calls) == 1
    assert no_sleep == []

@pytest.mark.parametrize("kwargs", [{"max_attempts": 0}, {"base_delay": -1.0}])
def test_retry_with_backoff_rejects_invalid_config(kwargs):
    with pytest.raises(ValueError):
        retry_with_backoff(**kwargs)

def test_retry_with_backoff_preserves_metadata():
    assert fetch_json.__name__ == "fetch_json"
    assert fetch_json.__doc__ is not None and "Retries" in fetch_json.__doc__

def test_backoff_delay_jitter_within_bounds():
    for attempt in range(1, 6):
        upper = 0.5 * 2 ** (attempt - 1)
        for _ in range(200):
            assert 0 <= _backoff_delay(attempt, 0.5) <= upper
