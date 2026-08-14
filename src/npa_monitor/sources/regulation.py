"""regulation.gov.ru — Федеральный портал проектов НПА.

Как это работает (замер 13.08.2026, подтверждено браузерным сеансом):
  * портал — Next.js без SSR карточек: HTML пустой, данные грузит клиент;
  * GET /api/public/Projects отдаёт HTTP 200 и totalCount, но поля пустые
    (title="", stage=Undefined). Фронт этим списком не пользуется;
  * реальный список — POST /api/public/PublicProjects/GetFiltered с JSON-телом.
    Тот же запрос проходит обычным HTTP-клиентом (Referer + application/json),
    браузерный рантайм не нужен;
  * поле публикации часто null, creationDate — заглушка 0001-01-01.
    Рабочая дата — startPublicDiscussion. Серверный фильтр по датам в теле
    не используем: лента отсортирована по убыванию id/даты, период режем
    на нашей стороне, как у cbr.ru.

Доступ прямой. Через датацентровый RU-прокси сайт не отвечает.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from ..http import Fetcher
from ..models import Document

log = logging.getLogger(__name__)

BASE = "https://regulation.gov.ru"
LIST_API = f"{BASE}/api/public/PublicProjects/GetFiltered"
STAGES_API = f"{BASE}/api/public/PublicProjects/GetProjectStages"
FILE_API = f"{BASE}/api/public/Files/GetFile"
PAGE_SIZE = 20

ORDERED_FIELDS = [
    "id",
    "npaStatistics",
    "title",
    "startPublicDiscussion",
    "endPublicDiscussion",
    "okveds",
    "developedDepartment",
    "stage",
    "status",
    "procedure",
]

STAGE_RU = {
    "Text": "Текст",
    "Notification": "Уведомление",
    "Grade": "Оценка",
}

STATUS_RU = {
    "Discussion": "Обсуждение",
    "Rejected": "Отклонён",
    "Completed": "Завершён",
    "Preparing": "Подготовка",
}


def _fetcher() -> Fetcher:
    fetcher = Fetcher("regulation")
    fetcher.session.headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": BASE,
            "Referer": f"{BASE}/",
        }
    )
    return fetcher


def _payload(page: int, page_size: int = PAGE_SIZE) -> dict:
    return {
        "listParams": {
            "filterModel": {
                "filters": "",
                "page": page,
                "pageSize": page_size,
            }
        },
        "orderedFields": ORDERED_FIELDS,
    }


def probe(page_size: int = 20) -> dict:
    """Проверить доступность и вернуть диагностику без сбора."""
    resp = _fetcher().post(LIST_API, json=_payload(1, page_size))
    data = resp.json()
    result = data.get("result") or []
    filled = [r for r in result if (r.get("title") or "").strip()]
    return {
        "reachable": True,
        "total_count": data.get("totalCount"),
        "returned": len(result),
        "with_content": len(filled),
        "note": "" if filled else "GetFiltered вернул записи без наименований.",
    }


def collect(date_from: str, date_to: str, max_pages: int = 50) -> list[Document]:
    """Собрать проекты, у которых начало обсуждения попадает в период."""
    lo = datetime.strptime(date_from, "%d.%m.%Y")
    hi = datetime.strptime(date_to, "%d.%m.%Y")
    fetcher = _fetcher()
    docs: list[Document] = []

    for page in range(1, max_pages + 1):
        resp = fetcher.post(LIST_API, json=_payload(page))
        data = resp.json()
        batch = data.get("result") or []
        if not batch:
            break

        dates = [_row_date(row) for row in batch]
        in_period_dates = [d for d in dates if d and lo <= d <= hi]
        include_undated = bool(in_period_dates)
        in_period = 0

        for row, dt in zip(batch, dates):
            if dt is None:
                if not include_undated:
                    continue
            elif not (lo <= dt <= hi):
                continue
            doc = _to_document(row, dt)
            if not doc:
                continue
            docs.append(doc)
            in_period += 1

        oldest = min((d for d in dates if d), default=None)
        log.info(
            "regulation: страница %s — в периоде %s (всего %s), самая ранняя %s",
            page,
            in_period,
            len(docs),
            oldest.strftime("%d.%m.%Y") if oldest else "—",
        )

        if oldest and oldest < lo:
            break

    return docs


def _row_date(row: dict) -> datetime | None:
    for key in ("startPublicDiscussion", "publicationDate"):
        dt = _parse_dt(row.get(key))
        if dt:
            return dt
    return None


def _parse_dt(value) -> datetime | None:
    if not value or str(value).startswith("0001-01-01"):
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _to_document(row: dict, dt: datetime | None) -> Document | None:
    pid = str(row.get("id") or "").strip()
    title = " ".join((row.get("title") or "").split())
    if not pid or not title:
        return None

    dept = row.get("developedDepartment")
    if isinstance(dept, dict):
        department = (dept.get("description") or "").strip()
    else:
        department = str(dept or "").strip()

    procedure = row.get("procedure")
    if isinstance(procedure, dict):
        doc_type = (procedure.get("description") or "").strip() or "Проект НПА"
    else:
        doc_type = "Проект НПА"

    date_text = dt.strftime("%d.%m.%Y") if dt else ""
    end_dt = _parse_dt(row.get("endPublicDiscussion"))
    status_parts = [
        _label(row.get("status"), STATUS_RU),
        _label(row.get("stage"), STAGE_RU),
    ]

    return Document(
        source="regulation.gov.ru",
        doc_type=doc_type,
        number=pid,
        title=title,
        publication_date=date_text,
        status_change_date=end_dt.strftime("%d.%m.%Y") if end_dt else date_text,
        status=" / ".join(p for p in status_parts if p),
        department=department,
        url=f"{BASE}/projects/{pid}/",
    )


def _label(value, mapping: dict[str, str]) -> str:
    if not value or str(value) == "Undefined":
        return ""
    text = str(value)
    return mapping.get(text, text)


def fetch_content(doc: Document, folder: Path) -> Path | None:
    """Скачать файлы этапов проекта. В колонку — текст проекта, иначе первый файл."""
    from ..content import write_bytes

    if not doc.number:
        return None
    fetcher = _fetcher()
    stages = fetcher.get(f"{STAGES_API}/{doc.number}").json()
    if not isinstance(stages, list):
        return None

    picked: list[tuple[bool, str, str]] = []
    seen: set[str] = set()
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        for key in ("file", "modifiedFile"):
            info = stage.get(key)
            if not isinstance(info, dict):
                continue
            file_id = str(info.get("fileId") or "").strip()
            if not file_id or file_id in seen:
                continue
            seen.add(file_id)
            name = (info.get("description") or info.get("id") or f"{file_id}.bin").strip()
            picked.append((stage.get("stage") == "Text", name, file_id))

    if not picked:
        return None

    primary: Path | None = None
    for is_text, name, file_id in picked:
        resp = fetcher.get(f"{FILE_API}/{file_id}")
        if not resp.content:
            continue
        path = write_bytes(
            folder,
            name,
            resp.content,
            content_type=resp.headers.get("Content-Type", ""),
            content_disposition=resp.headers.get("Content-Disposition", ""),
        )
        if is_text or primary is None:
            primary = path
    return primary
