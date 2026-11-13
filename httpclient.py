import functools
import logging
import random
import time
from collections.abc import Callable
from typing import ParamSpec, TypeVar

import requests

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

# Status codes that usually mean "try again shortly": rate limiting (429) and
# gateway/upstream unavailability (502/503/504). Other 4xx are caller errors.
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 502, 503, 504})
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 0.5

def _is_transient(exc: Exception) -> bool:
    """Return True if the error is likely to clear up on its own if we retry."""
    if isinstance(exc, requests.Timeout):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return False

def _backoff_delay(attempt: int, base_delay: float) -> float:
    """Exponential backoff with full jitter.

    Picking uniformly in [0, base * 2**(attempt-1)] spreads clients across the
    window so they don't all retry in lockstep (thundering herd).
    """
    return random.uniform(0, base_delay * 2 ** (attempt - 1))

def _describe(exc: Exception) -> str:
    """Short, log-friendly reason for a failure."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, requests.Timeout):
        return f"Timeout: {type(exc).__name__}"
    return f"{type(exc).__name__}: {exc}"

def retry_with_backoff(
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry a call on transient failures, with exponential backoff and jitter.

    Why: external APIs blip (timeouts, rate limits, gateway errors during
    deploys), and one blip shouldn't fail the whole CLI run. Jitter keeps many
    clients from retrying in sync and re-overloading the server. Non-transient
    errors (e.g. 400/401/404, 500) are bugs or permanent conditions, so they
    are raised immediately rather than wasting time on retries.

    Every retry and every final failure is logged. After the last attempt the
    original exception is re-raised unchanged, so callers can keep catching
    ``requests.HTTPError`` / ``requests.Timeout`` as before.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    if base_delay < 0:
        raise ValueError(f"base_delay must be >= 0, got {base_delay}")

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    reason = _describe(exc)
                    if not _is_transient(exc):
                        logger.error(
                            "%s failed with non-retryable error: %s",
                            func.__name__, reason,
                        )
                        raise
                    if attempt == max_attempts:
                        logger.error(
                            "%s giving up after %d attempts: %s",
                            func.__name__, max_attempts, reason,
                        )
                        raise
                    delay = _backoff_delay(attempt, base_delay)
                    logger.warning(
                        "%s attempt %d/%d failed (%s); retrying in %.2fs",
                        func.__name__, attempt, max_attempts, reason, delay,
                    )
                    time.sleep(delay)
            raise AssertionError("unreachable")  # loop always returns or raises
        return wrapper
    return decorator

@retry_with_backoff()
def fetch_json(url: str) -> dict:
    """Fetch ``url`` and return the decoded JSON body.

    Retries up to 3 attempts total (0.5s base delay, exponential backoff with
    jitter) on timeouts and HTTP 429/502/503/504. Any other HTTP error fails
    immediately. If all attempts fail, the last exception is re-raised.
    """
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    return response.json()
