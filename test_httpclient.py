import logging

import pytest
import requests

import httpclient
from httpclient import fetch_json, retry_with_backoff


def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []
    monkeypatch.setattr(httpclient.time, "sleep", delays.append)
    monkeypatch.setattr(httpclient.random, "uniform", lambda _a, _b: 0.5)
    return delays


def test_fetch_json_success(requests_mock):
    requests_mock.get("https://example.com/data", json={"ok": True})
    result = fetch_json("https://example.com/data")
    assert result == {"ok": True}


def test_fetch_json_raises_on_error(requests_mock):
    requests_mock.get("https://example.com/data", status_code=500)
    with pytest.raises(requests.HTTPError):
        fetch_json("https://example.com/data")


def test_fetch_json_succeeds_on_first_try(monkeypatch, requests_mock):
    delays = _patch_sleep(monkeypatch)
    requests_mock.get("https://example.com/data", json={"ok": True})

    result = fetch_json("https://example.com/data")

    assert result == {"ok": True}
    assert requests_mock.call_count == 1
    assert delays == []


def test_fetch_json_succeeds_after_retry(monkeypatch, requests_mock, caplog):
    delays = _patch_sleep(monkeypatch)
    requests_mock.get(
        "https://example.com/data",
        [
            {"status_code": 503, "text": "unavailable"},
            {"status_code": 200, "json": {"ok": True}},
        ],
    )

    with caplog.at_level(logging.WARNING):
        result = fetch_json("https://example.com/data")

    assert result == {"ok": True}
    assert requests_mock.call_count == 2
    assert delays == [0.25]
    assert any("retry attempt 1/3" in record.message for record in caplog.records)


def test_fetch_json_exhausts_retries(monkeypatch, requests_mock, caplog):
    delays = _patch_sleep(monkeypatch)
    requests_mock.get("https://example.com/data", status_code=503, text="unavailable")

    with caplog.at_level(logging.WARNING), pytest.raises(requests.HTTPError):
        fetch_json("https://example.com/data")

    assert requests_mock.call_count == 3
    assert delays == [0.25, 0.5]
    assert any("request failed on attempt 3/3" in record.message for record in caplog.records)


def test_fetch_json_fails_fast_on_client_error(monkeypatch, requests_mock):
    delays = _patch_sleep(monkeypatch)
    requests_mock.get("https://example.com/data", status_code=404, text="missing")

    with pytest.raises(requests.HTTPError):
        fetch_json("https://example.com/data")

    assert requests_mock.call_count == 1
    assert delays == []


def test_retry_with_backoff_on_stub(monkeypatch):
    delays = _patch_sleep(monkeypatch)
    calls = {"n": 0}

    @retry_with_backoff(max_attempts=3, base_delay=0.5)
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.Timeout("timed out")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3
    assert delays == [0.25, 0.5]
