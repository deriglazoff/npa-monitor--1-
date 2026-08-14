"""Единая схема документа — общая для всех трёх источников.

Поля соответствуют колонкам итоговой выгрузки из технического задания:
источник, тип, номер, наименование, дата публикации, дата смены статуса,
статус, ведомство, прямая ссылка.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

COLUMNS = [
    "source",
    "doc_type",
    "number",
    "title",
    "publication_date",
    "status_change_date",
    "status",
    "department",
    "url",
    "content_path",
    "topics",
    "keywords",
]

HEADERS_RU = {
    "source": "Источник",
    "doc_type": "Тип документа",
    "number": "Номер",
    "title": "Наименование",
    "publication_date": "Дата публикации",
    "status_change_date": "Дата смены статуса",
    "status": "Статус / стадия",
    "department": "Ведомство",
    "url": "Ссылка на портал",
    "content_path": "Файл",
    "topics": "Направления",
    "keywords": "Сработавшие слова",
}


@dataclass
class Document:
    source: str
    doc_type: str = ""
    number: str = ""
    title: str = ""
    publication_date: str = ""
    status_change_date: str = ""
    status: str = ""
    department: str = ""
    url: str = ""
    content_path: str = ""
    topics: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def as_row(self) -> dict:
        d = asdict(self)
        d["topics"] = "; ".join(self.topics)
        d["keywords"] = "; ".join(self.keywords)
        return d

    def searchable_text(self) -> str:
        return " ".join([self.title, self.doc_type, self.status, self.department])
