"""Validation of values a person types before they reach adb.

adb is never run through a shell, so these checks are not the injection
defence. They exist so that a typo produces a clear message, and so that a
value starting with ``-`` can never be mistaken for an adb option.
"""

from __future__ import annotations

import ipaddress
import re

_HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$")
_PAIR_CODE = re.compile(r"^\d{6}$")


class ValidationError(ValueError):
    """``code`` is a stable key the UI translates."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def host(value: str) -> str:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    if not value:
        raise ValidationError("host_empty")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if _HOSTNAME.match(value) and not value.replace(".", "").isdigit():
        return value
    raise ValidationError("host_invalid")


def port(value: str | int) -> int:
    text = str(value).strip()
    if not text:
        raise ValidationError("port_empty")
    if not text.isdigit():
        raise ValidationError("port_invalid")
    number = int(text)
    if not 1 <= number <= 65535:
        raise ValidationError("port_invalid")
    return number


def pair_code(value: str) -> str:
    text = value.replace(" ", "").replace("-", "").strip()
    if not _PAIR_CODE.match(text):
        raise ValidationError("code_invalid")
    return text


def endpoint(host_value: str, port_value: int) -> str:
    """``host:port`` as adb expects it (IPv6 in brackets)."""
    if ":" in host_value:
        return f"[{host_value}]:{port_value}"
    return f"{host_value}:{port_value}"


def split_endpoint(text: str, default_port: int | None = None) -> tuple[str, int]:
    """Parse ``host``, ``host:port`` or ``[v6]:port``."""
    text = text.strip()
    if text.startswith("["):
        close = text.find("]")
        if close == -1:
            raise ValidationError("host_invalid")
        host_part, rest = text[1:close], text[close + 1 :]
        if rest.startswith(":"):
            return host(host_part), port(rest[1:])
        if rest:
            raise ValidationError("host_invalid")
        if default_port is None:
            raise ValidationError("port_empty")
        return host(host_part), default_port
    if text.count(":") == 1:
        host_part, port_part = text.split(":")
        return host(host_part), port(port_part)
    if default_port is None:
        raise ValidationError("port_empty")
    return host(text), default_port
