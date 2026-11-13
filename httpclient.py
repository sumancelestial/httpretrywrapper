import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

import requests

logger = logging.getLogger(__name__)
T = TypeVar("T")
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


def _is_retryable_error(error: Exception) -> bool:
    if isinstance(error, requests.exceptions.Timeout):
        return True
    return (
        isinstance(error, requests.exceptions.HTTPError)
        and error.response is not None
        and error.response.status_code in RETRYABLE_STATUS_CODES
    )


def retry_with_backoff(
    operation: Callable[[], T],
    max_attempts: int = 3,
    base_delay: float = 0.5,
) -> T:
    """Retry transient request failures with jitter to reduce synchronized retries."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if base_delay < 0:
        raise ValueError("base_delay cannot be negative")

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as error:
            if not _is_retryable_error(error):
                logger.exception("Request failed without retry")
                raise
            if attempt == max_attempts:
                logger.exception(
                    "Request failed after %s attempts",
                    max_attempts,
                )
                raise

            exponential_delay = base_delay * 2 ** (attempt - 1)
            delay = random.uniform(exponential_delay / 2, exponential_delay)
            logger.warning(
                "Retrying request (attempt %s/%s) in %.2f seconds: %s",
                attempt,
                max_attempts,
                delay,
                error,
            )
            time.sleep(delay)

    raise RuntimeError("retry loop exited unexpectedly")


def fetch_json(url: str) -> dict:
    """Fetch JSON, retrying transient failures with jittered exponential backoff."""

    def fetch() -> dict:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()

    return retry_with_backoff(fetch)
