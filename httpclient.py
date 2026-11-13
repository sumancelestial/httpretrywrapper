import logging
import random
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

import requests

logger = logging.getLogger(__name__)

# Transient HTTP statuses: rate limiting and the gateway/availability errors
# that usually indicate a short-lived upstream problem. Every other client
# error (4xx) would fail identically if replayed, so those are permanent.
RETRYABLE_STATUSES = {429, 502, 503, 504}

F = TypeVar("F", bound=Callable[..., Any])


def _is_retryable(exc: Exception) -> bool:
    """Return True only for transient failures worth retrying.

    Timeouts and 429/502/503/504 responses typically resolve on their own,
    so they are retried; anything else — other 4xx errors included — would
    fail the same way if replayed, so it must fail fast.
    """
    if isinstance(exc, requests.exceptions.Timeout):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status in RETRYABLE_STATUSES
    return False


def retry_with_backoff(
    max_attempts: int = 3, base_delay: float = 0.5
) -> Callable[[F], F]:
    """Decorator retrying a call on transient errors with jittered backoff.

    External APIs fail transiently (timeouts, 429, 502/503/504); without
    retries those blips become hard failures. This wrapper retries only
    transient errors, waits between attempts with exponential backoff plus
    full jitter (random.uniform(0, delay)) so many clients waking up at the
    same moment do not stampede the server, and re-raises immediately on
    anything non-transient so bad requests fail fast. Every retry and every
    give-up is logged rather than silently absorbed.
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if not _is_retryable(exc):
                        logger.error(
                            "Non-retryable error in %s (attempt %d of %d), "
                            "failing fast: %r",
                            func.__name__,
                            attempt,
                            max_attempts,
                            exc,
                        )
                        raise
                    if attempt >= max_attempts:
                        logger.error(
                            "Retries exhausted for %s after %d of %d "
                            "attempts: %r",
                            func.__name__,
                            attempt,
                            max_attempts,
                            exc,
                        )
                        raise
                    delay = base_delay * (2 ** (attempt - 1))
                    sleep_time = random.uniform(0, delay)
                    logger.warning(
                        "Transient error in %s (attempt %d of %d): %r; "
                        "retrying in %.2fs",
                        func.__name__,
                        attempt,
                        max_attempts,
                        exc,
                        sleep_time,
                    )
                    time.sleep(sleep_time)

        return cast(F, wrapper)

    return decorator


@retry_with_backoff()
def fetch_json(url: str) -> dict:
    """Fetch and parse JSON from ``url``, retrying transient failures.

    Timeouts and 429/502/503/504 responses are retried up to ``max_attempts``
    total attempts (3 by default) with jittered exponential backoff (0.5s
    base delay); any other error — including 4xx client errors — is raised
    immediately, without retrying.
    """
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    return response.json()
