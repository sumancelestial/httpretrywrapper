import pytest
import requests

from httpclient import fetch_json, retry_with_backoff


def test_retry_with_backoff_succeeds_first_try():
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        return {"ok": True}

    result = retry_with_backoff(operation)

    assert result == {"ok": True}
    assert calls == 1


def test_retry_with_backoff_retries_then_succeeds(monkeypatch, caplog):
    calls = 0
    jitter_bounds = []
    delays = []

    def operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise requests.exceptions.Timeout("temporary timeout")
        return {"ok": True}

    def deterministic_jitter(lower, upper):
        jitter_bounds.append((lower, upper))
        return (lower + upper) / 2

    monkeypatch.setattr("httpclient.random.uniform", deterministic_jitter)
    monkeypatch.setattr("httpclient.time.sleep", delays.append)

    result = retry_with_backoff(operation)

    assert result == {"ok": True}
    assert calls == 3
    assert jitter_bounds == [(0.25, 0.5), (0.5, 1.0)]
    assert delays == [0.375, 0.75]
    assert "Retrying request" in caplog.text


@pytest.mark.parametrize("status_code", [429, 502, 503, 504])
def test_retry_with_backoff_retries_transient_http_statuses(status_code, monkeypatch):
    calls = 0
    response = requests.Response()
    response.status_code = status_code
    error = requests.exceptions.HTTPError("transient response", response=response)

    def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error
        return {"ok": True}

    monkeypatch.setattr("httpclient.time.sleep", lambda _: None)

    result = retry_with_backoff(operation, base_delay=0)

    assert result == {"ok": True}
    assert calls == 2


def test_retry_with_backoff_raises_after_max_attempts(monkeypatch, caplog):
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        raise requests.exceptions.Timeout("temporary timeout")

    monkeypatch.setattr("httpclient.time.sleep", lambda _: None)

    with pytest.raises(requests.exceptions.Timeout):
        retry_with_backoff(operation, max_attempts=2, base_delay=0)

    assert calls == 2
    assert "Request failed after 2 attempts" in caplog.text


def test_retry_with_backoff_fails_fast_on_non_retryable_error(monkeypatch, caplog):
    calls = 0
    response = requests.Response()
    response.status_code = 400
    error = requests.exceptions.HTTPError("bad request", response=response)

    def operation():
        nonlocal calls
        calls += 1
        raise error

    monkeypatch.setattr("httpclient.time.sleep", lambda _: None)

    with pytest.raises(requests.exceptions.HTTPError):
        retry_with_backoff(operation)

    assert calls == 1
    assert "Request failed without retry" in caplog.text


def test_fetch_json_success(requests_mock):
    requests_mock.get("https://example.com/data", json={"ok": True})
    result = fetch_json("https://example.com/data")
    assert result == {"ok": True}


def test_fetch_json_retries_transient_error(requests_mock, monkeypatch):
    requests_mock.get(
        "https://example.com/data",
        [{"status_code": 503}, {"json": {"ok": True}}],
    )
    monkeypatch.setattr("httpclient.time.sleep", lambda _: None)

    result = fetch_json("https://example.com/data")

    assert result == {"ok": True}
    assert len(requests_mock.request_history) == 2


def test_fetch_json_raises_on_error(requests_mock):
    requests_mock.get("https://example.com/data", status_code=500)
    with pytest.raises(requests.exceptions.HTTPError):
        fetch_json("https://example.com/data")
