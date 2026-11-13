from httpclient import fetch_json

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