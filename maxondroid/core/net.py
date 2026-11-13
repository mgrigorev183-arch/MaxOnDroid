"""The only way MaxOnDroid talks to the internet: an HTTPS GET with a size limit.

Two places use it, both started by the user or allowed in the settings: the
UAD-ng list download and the update check. Certificates are always verified,
plain HTTP is refused, and a redirect may not leave HTTPS (urllib would follow
an https -> http redirect by itself). Nothing about the user or their devices
is sent: no cookies, no identifiers, only the request line and a User-Agent.
"""

from __future__ import annotations

import ssl
import urllib.request
from collections.abc import Callable

from maxondroid import __version__

USER_AGENT = f"MaxOnDroid/{__version__}"


class NetError(OSError):
    """``code``: insecure_url, too_large, network."""

    def __init__(self, code: str, details: str = ""):
        super().__init__(details or code)
        self.code = code
        self.details = details


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        if not newurl.lower().startswith("https://"):
            raise NetError("insecure_url", newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_open(request: urllib.request.Request, timeout: float):
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _HttpsOnlyRedirects())
    return opener.open(request, timeout=timeout)


Opener = Callable[[urllib.request.Request, float], object]


def fetch(url: str, max_bytes: int, timeout: float = 15.0, headers: dict[str, str] | None = None, opener: Opener | None = None) -> bytes:
    """GET ``url`` and return at most ``max_bytes`` bytes, or raise NetError."""
    if not url.lower().startswith("https://"):
        raise NetError("insecure_url", url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    open_url = opener or _default_open
    try:
        with open_url(request, timeout) as response:
            raw = response.read(max_bytes + 1)
    except NetError:
        raise
    except (OSError, ValueError) as exc:  # URLError, HTTPError, socket and TLS errors are OSError
        raise NetError("network", str(exc)) from exc
    if len(raw) > max_bytes:
        raise NetError("too_large", str(len(raw)))
    return raw
