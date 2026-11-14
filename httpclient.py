import logging
import random
import time
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

import requests

logger = logging.getLogger(__name__)

TRANSIENT_STATUS_CODES = frozenset({429, 502, 503, 504})

P = ParamSpec("P")
T = TypeVar("T")


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, requests.Timeout):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code in TRANSIENT_STATUS_CODES
    return False


def _backoff_delay(base_delay: float, attempt: int) -> float:
    """Spread retries so simultaneous callers do not retry in lockstep."""
    delay = base_delay * (2 ** (attempt - 1))
    return delay * random.uniform(0.5, 1.0)


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 0.5,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Retry transient HTTP failures so a brief outage does not fail the call.

    Jittered exponential backoff keeps retries from stampeding the server
    when many callers fail at the same time. Non-transient errors fail
    immediately because retrying them cannot succeed.
    """

    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        @wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    if not _is_transient(exc) or attempt == max_attempts:
                        logger.error(
                            "request failed on attempt %s/%s: %s",
                            attempt,
                            max_attempts,
                            exc,
                        )
                        raise
                    delay = _backoff_delay(base_delay, attempt)
                    logger.warning(
                        "retry attempt %s/%s after %.3fs: %s",
                        attempt,
                        max_attempts,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
            raise RuntimeError("retry loop exited without a result")

        return wrapper

    return decorator


@retry_with_backoff()
def fetch_json(url: str) -> dict:
    """Fetch JSON, retrying timeouts and transient statuses so a short blip does not fail the caller."""
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    return response.json()
