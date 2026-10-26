"""Enmascarado de datos personales (email, teléfono, documento de identidad).

Por defecto se enmascaran (CLOUDBEDS_SHOW_PII=false). Solo se muestran tal
cual cuando show_pii es True.
"""

from __future__ import annotations

import re

MASK = "***"


def mask_email(value: str | None) -> str | None:
    """juan.perez@gmail.com -> j***@g***.com"""
    if not value:
        return value
    value = value.strip()
    if "@" not in value:
        return MASK
    local, _, domain = value.partition("@")
    host, dot, tld = domain.rpartition(".")
    if not dot:  # dominio sin punto
        host, tld = domain, ""
    masked_domain = f"{host[:1]}{MASK}" + (f".{tld}" if tld else "")
    return f"{local[:1]}{MASK}@{masked_domain}"


def mask_phone(value: str | None) -> str | None:
    """+51 987 654 321 -> ***321 (solo los 3 últimos dígitos)."""
    if not value:
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) <= 3:
        return MASK
    return f"{MASK}{digits[-3:]}"


def mask_document(value: str | None) -> str | None:
    """12345678 -> ***78 (solo los 2 últimos caracteres)."""
    if not value:
        return value
    clean = re.sub(r"\s", "", value)
    if len(clean) <= 2:
        return MASK
    return f"{MASK}{clean[-2:]}"


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_LONG_NUMBER_RE = re.compile(r"\+?\d[\d\s().-]{5,}\d")


def scrub_text(value: str | None, show_pii: bool) -> str | None:
    """Enmascara emails y números largos (teléfonos, documentos) dentro de texto libre."""
    if not value or show_pii:
        return value
    value = _EMAIL_RE.sub(lambda m: mask_email(m.group(0)) or MASK, value)
    return _LONG_NUMBER_RE.sub(lambda m: mask_phone(m.group(0)) or MASK, value)


def email(value: str | None, show_pii: bool) -> str | None:
    return value if show_pii else mask_email(value)


def phone(value: str | None, show_pii: bool) -> str | None:
    return value if show_pii else mask_phone(value)


def document(value: str | None, show_pii: bool) -> str | None:
    return value if show_pii else mask_document(value)
