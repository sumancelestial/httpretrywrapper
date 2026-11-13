
import pytest
import requests
from unittest.mock import Mock, patch

from httpclient import fetch_json


URL = "https://example.com/data"


def mock_response(status_code, payload=None):
    """Create a simulated HTTP response."""
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload or {"ok": True}

    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"HTTP {status_code}",
            response=response
        )

    return response


def test_success_on_first_attempt():
    response = mock_response(200, {"message": "success"})

    with patch("httpclient.requests.get", return_value=response) as mock_get:
        result = fetch_json(URL)

        assert result == {"message": "success"}
        assert mock_get.call_count == 1

    print("PASS: First attempt success")


def test_retry_then_success():
    responses = [
        mock_response(503),
        mock_response(503),
        mock_response(200, {"message": "recovered"})
    ]

    with patch("httpclient.requests.get", side_effect=responses) as mock_get:
        result = fetch_json(URL)

        assert result == {"message": "recovered"}
        assert mock_get.call_count == 3

    print("PASS: Retry then success")


def test_failure_after_max_attempts():
    response = mock_response(503)

    with patch("httpclient.requests.get", return_value=response) as mock_get:
        with pytest.raises(requests.HTTPError):
            fetch_json(URL)

        assert mock_get.call_count == 3

    print("PASS: Maximum attempts exhausted")


def test_non_retryable_error():
    response = mock_response(401)

    with patch("httpclient.requests.get", return_value=response) as mock_get:
        with pytest.raises(requests.HTTPError):
            fetch_json(URL)

        assert mock_get.call_count == 1

    print("PASS: Non-retryable error fails immediately")


def test_timeout_then_success():
    success_response = mock_response(200, {"message": "recovered"})

    with patch(
        "httpclient.requests.get",
        side_effect=[
            requests.Timeout("Connection timed out"),
            success_response
        ]
    ) as mock_get:

        result = fetch_json(URL)

        assert result == {"message": "recovered"}
        assert mock_get.call_count == 2

    print("PASS: Timeout retry")