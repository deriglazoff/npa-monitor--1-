"""regulation.gov.ru — Федеральный портал проектов НПА.

ЧАСТИЧНО РАБОТАЮЩИЙ ИСТОЧНИК. Читайте раздел «Ограничения» в README.

Что установлено замером 13.08.2026:
  * портал доступен напрямую (HTTP 200, ~715 КБ), гео-блокировки нет;
  * это Next.js-приложение без server-side рендера карточек: HTML содержит
    только оболочку, данные подгружаются на клиенте;
  * найден рабочий публичный эндпоинт списка:
        GET /api/public/Projects?page=N&pageSize=M
    он отдаёт HTTP 200, JSON и корректный totalCount (127 927 записей),
    НО все содержательные поля в ответе пустые: title="", stage="Undefined",
    creationDate="0001-01-01", publicationDate=null. Приходят только id;
  * детальные эндпоинты (/api/public/Projects/{id}, .../Detail/{id},
    .../ProjectDetails/{id}), а также api.regulation.gov.ru и /sitemap.xml
    не отвечают вовсе — соединение виснет до таймаута (не 404, а обрыв);
  * RSC-запрос карточки (заголовок RSC: 1) отдаёт 5 КБ без данных проекта.

Вывод: наполнение карточек закрыто для серверных клиентов. Чтобы получить
поля (наименование, ведомство, статус, даты), нужен либо реальный браузерный
сеанс (headless Chromium с исполнением JS), либо найденный через DevTools
POST-эндпоинт поиска, который фронтенд вызывает с телом запроса.

Модуль сознательно НЕ притворяется, что источник собран: он возвращает
перечень идентификаторов и ссылок, а фактическую неполноту сообщает наружу
через SourceResult.status = "partial", чтобы это попало в отчёт и в README,
а не растворилось в пустой выгрузке.
"""

from __future__ import annotations

import logging

from ..http import Fetcher
from ..models import Document

log = logging.getLogger(__name__)

BASE = "https://regulation.gov.ru"
LIST_API = f"{BASE}/api/public/Projects"

NOTE = (
    "Портал отдаёт только идентификаторы проектов: публичный API возвращает "
    "записи с пустыми полями, детальные эндпоинты не отвечают. Для наполнения "
    "карточек требуется браузерный сеанс с исполнением JS."
)


def probe(page_size: int = 20) -> dict:
    """Проверить доступность и вернуть диагностику без сбора."""
    fetcher = Fetcher("regulation")
    resp = fetcher.get(LIST_API, params={"page": "1", "pageSize": str(page_size)})
    data = resp.json()
    result = data.get("result") or []
    filled = [r for r in result if (r.get("title") or "").strip()]
    return {
        "reachable": True,
        "total_count": data.get("totalCount"),
        "returned": len(result),
        "with_content": len(filled),
        "note": NOTE if not filled else "",
    }


def collect(date_from: str, date_to: str, max_pages: int = 50) -> list[Document]:
    """Собрать то, что портал реально отдаёт серверному клиенту.

    Фильтрация по датам на стороне портала недоступна (поля дат пустые),
    поэтому период здесь не применяется — он остаётся в сигнатуре ради
    единообразия с остальными источниками.
    """
    fetcher = Fetcher("regulation")
    docs: list[Document] = []

    for page in range(1, max_pages + 1):
        resp = fetcher.get(LIST_API, params={"page": str(page), "pageSize": "20"})
        data = resp.json()
        batch = data.get("result") or []
        if not batch:
            break

        for row in batch:
            pid = str(row.get("id") or "").strip()
            if not pid:
                continue
            title = (row.get("title") or "").strip()
            docs.append(
                Document(
                    source="regulation.gov.ru",
                    doc_type=(row.get("projectType") or "Проект НПА"),
                    number=pid,
                    title=title,
                    publication_date=_date(row.get("publicationDate")),
                    status_change_date=_date(row.get("creationDate")),
                    status=_enum(row.get("stage")) or _enum(row.get("status")),
                    department=(row.get("developedDepartment") or ""),
                    url=f"{BASE}/projects/{pid}/",
                )
            )

        log.info("regulation: страница %s — %s записей (всего %s)", page, len(batch), len(docs))

    return docs


def _date(value) -> str:
    """ISO-дата портала → ДД.ММ.ГГГГ. Пустые заглушки отбрасываются."""
    if not value or str(value).startswith("0001-01-01"):
        return ""
    text = str(value)[:10]
    parts = text.split("-")
    if len(parts) != 3:
        return ""
    return f"{parts[2]}.{parts[1]}.{parts[0]}"


def _enum(value) -> str:
    if not value or str(value) == "Undefined":
        return ""
    return str(value)
