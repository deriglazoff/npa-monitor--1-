"""Источники данных. Каждый модуль экспортирует collect(date_from, date_to, max_pages)."""

from . import cbr, regulation, sozd

REGISTRY = {
    "sozd": sozd,
    "cbr": cbr,
    "regulation": regulation,
}

__all__ = ["REGISTRY", "cbr", "regulation", "sozd"]
