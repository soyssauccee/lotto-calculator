import pytest
import requests

from lottocalc.http import USER_AGENT, FetchError, PoliteSession


def response(status=200, body="ok", content_type="text/html"):
    r = requests.Response()
    r.status_code = status
    r._content = body.encode("utf-8")
    r.headers["Content-Type"] = content_type
    return r


class FakeRequests:
    """Plays back a script of responses or exceptions, one per request."""

    def __init__(self, *script):
        self.script = list(script)
        self.headers = {}
        self.calls = 0

    def get(self, url, timeout):
        self.calls += 1
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def session(*script):
    polite = PoliteSession(delay=0, backoff=0)
    polite._session = FakeRequests(*script)
    return polite


def test_identifies_itself():
    assert PoliteSession()._session.headers["User-Agent"] == USER_AGENT


def test_retries_a_cut_off_download_then_succeeds():
    polite = session(requests.exceptions.ChunkedEncodingError("connection broken"), response(body="page"))
    assert polite.get("https://example.com/a") == "page"
    assert polite.requests_made == 2


def test_retries_server_errors():
    polite = session(response(503), response(429), response(body="page"))
    assert polite.get("https://example.com/a") == "page"
    assert polite.requests_made == 3


def test_gives_up_after_the_retries():
    polite = session(requests.ConnectionError("down"), requests.Timeout("slow"), requests.ConnectionError("down"))
    with pytest.raises(FetchError, match="down"):
        polite.get("https://example.com/a")
    assert polite.requests_made == 3


def test_does_not_retry_a_missing_page():
    polite = session(response(404))
    with pytest.raises(FetchError, match="HTTP 404"):
        polite.get("https://example.com/a")
    assert polite.requests_made == 1


def test_pages_without_a_charset_are_read_as_utf8():
    polite = session(response(body="Win or Share – $100,000 × 60", content_type="text/html"))
    assert polite.get("https://example.com/a") == "Win or Share – $100,000 × 60"
