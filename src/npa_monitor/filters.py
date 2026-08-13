"""Тематический фильтр по направлениям из config.yaml.

Сознательно простое сопоставление по основе слова, без морфологии: словарь
задаётся усечёнными основами («кредитован», «взыскани»), что покрывает падежи
без внешних зависимостей вроде pymorphy. Ложные срабатывания лечатся правкой
config.yaml, а не кодом.
"""

from __future__ import annotations

import re

from .models import Document

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _WS.sub(" ", text.lower().replace("ё", "е")).strip()


def match(doc: Document, topics: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """Вернуть (сработавшие направления, сработавшие ключевые слова)."""
    haystack = normalize(doc.searchable_text())
    hit_topics: list[str] = []
    hit_words: list[str] = []

    for topic, words in topics.items():
        for word in words:
            needle = normalize(word)
            if needle and needle in haystack:
                if topic not in hit_topics:
                    hit_topics.append(topic)
                if word not in hit_words:
                    hit_words.append(word)

    return hit_topics, hit_words


def apply(docs: list[Document], topics: dict[str, list[str]]) -> list[Document]:
    """Оставить документы, попавшие хотя бы в одно направление."""
    kept: list[Document] = []
    for doc in docs:
        hit_topics, hit_words = match(doc, topics)
        if hit_topics:
            doc.topics = hit_topics
            doc.keywords = hit_words
            kept.append(doc)
    return kept
