"""HTTP client that stays polite to the sites being scraped.

Every request carries an identifiable User-Agent, requests to the same host are
spaced out, and only transient failures (timeouts, 429, 5xx) are retried.
"""
import time
from urllib.parse import urlsplit

import requests

USER_AGENT = "lotto-calculator/0.1 (personal non-commercial project; ~3 requests per draw)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """A page could not be downloaded."""


class PoliteSession:
    def __init__(self, delay=1.5, timeout=30, retries=2, backoff=10.0):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.requests_made = 0
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._last_request = {}

    def get(self, url):
        """Return the body of url as text, or raise FetchError."""
        host = urlsplit(url).netloc
        problem = None
        for attempt in range(self.retries + 1):
            if attempt:
                time.sleep(self.backoff * attempt)
            self._wait_turn(host)
            try:
                response = self._session.get(url, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                problem = exc
                continue
            finally:
                self._last_request[host] = time.monotonic()
                self.requests_made += 1
            if response.status_code in RETRYABLE_STATUS:
                problem = f"HTTP {response.status_code}"
                continue
            if response.status_code != 200:
                raise FetchError(f"{url}: HTTP {response.status_code}")
            if "charset" not in response.headers.get("Content-Type", "").lower():
                response.encoding = "utf-8"
            return response.text
        raise FetchError(f"{url}: {problem}")

    def _wait_turn(self, host):
        wait = self._last_request.get(host, float("-inf")) + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
