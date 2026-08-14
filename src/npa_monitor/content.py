"""Сохранение содержания документов рядом с CSV/XLSX."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

from .models import Document

log = logging.getLogger(__name__)

SOURCE_SLUG = {
    "regulation.gov.ru": "regulation",
    "cbr.ru": "cbr",
    "sozd.duma.gov.ru": "sozd",
}

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
FILE_EXTS = (".pdf", ".doc", ".docx", ".rtf", ".xls", ".xlsx")
_KNOWN_EXT = {".pdf", ".doc", ".docx", ".rtf", ".xls", ".xlsx", ".html", ".htm", ".zip", ".pptx"}
_WEAK_EXT = {".bin", ".dat", ".tmp", ""}
_OLE = bytes.fromhex("D0CF11E0A1B11AE1")
_CT_EXT = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/rtf": ".rtf",
    "text/rtf": ".rtf",
    "text/html": ".html",
    "application/zip": ".zip",
}


def safe_name(name: str, fallback: str = "file") -> str:
    cleaned = _UNSAFE.sub("_", name).strip(" .")
    return (cleaned or fallback)[:180]


def guess_ext(data: bytes, content_type: str = "") -> str:
    """Расширение по сигнатуре, иначе по Content-Type."""
    if data.startswith(b"%PDF"):
        return ".pdf"
    if data.startswith(b"PK"):
        head = data[:8192]
        if b"word/" in head or b"wordprocessingml" in head:
            return ".docx"
        if b"xl/" in head or b"spreadsheetml" in head:
            return ".xlsx"
        if b"ppt/" in head:
            return ".pptx"
        return ".zip"
    if data.startswith(_OLE):
        return ".doc"
    stripped = data.lstrip()
    if stripped.startswith(b"{\\rtf"):
        return ".rtf"
    low = stripped[:32].lower()
    if low.startswith(b"<!doctype html") or low.startswith(b"<html"):
        return ".html"
    ct = (content_type or "").split(";")[0].strip().lower()
    return _CT_EXT.get(ct, "")


def filename_from_disposition(header: str) -> str:
    if not header:
        return ""
    starred = re.search(r"filename\*=(?:UTF-8''|utf-8'')([^;]+)", header, re.I)
    if starred:
        from urllib.parse import unquote

        return unquote(starred.group(1).strip().strip('"'))
    quoted = re.search(r'filename="([^"]+)"', header, re.I)
    if quoted:
        return quoted.group(1)
    plain = re.search(r"filename=([^;]+)", header, re.I)
    if plain:
        return plain.group(1).strip().strip('"')
    return ""


def resolve_filename(
    suggested: str,
    data: bytes,
    content_type: str = "",
    content_disposition: str = "",
) -> str:
    from_disp = filename_from_disposition(content_disposition)
    if from_disp:
        suggested = from_disp
    suggested = safe_name(suggested or "attachment", "attachment")
    guessed = guess_ext(data, content_type)
    stem = Path(suggested).stem or "attachment"
    current = Path(suggested).suffix.lower()
    if current in _WEAK_EXT or not current:
        return stem + (guessed or ".bin")
    if guessed and current not in _KNOWN_EXT:
        return stem + guessed
    return suggested


def write_bytes(
    folder: Path,
    filename: str,
    data: bytes,
    *,
    content_type: str = "",
    content_disposition: str = "",
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    name = resolve_filename(filename, data, content_type, content_disposition)
    path = folder / name
    path.write_bytes(data)
    return path


def doc_folder(content_root: Path, doc: Document) -> Path:
    slug = SOURCE_SLUG.get(doc.source, safe_name(doc.source, "src"))
    ident = safe_name(doc.number, "") if doc.number else ""
    if not ident:
        ident = safe_name(doc.url.replace("https://", "").replace("/", "_"), "item")
    return content_root / slug / ident


def looks_like_file(href: str) -> bool:
    low = href.lower().split("?")[0]
    return any(low.endswith(ext) for ext in FILE_EXTS) or "/download" in low


def filename_from_url(url: str, fallback: str) -> str:
    from urllib.parse import unquote, urlparse

    name = Path(unquote(urlparse(url).path)).name
    return name or fallback


def relative_to_out(path: Path, out_dir: Path) -> str:
    return path.resolve().relative_to(out_dir.resolve()).as_posix()


def attach_content(
    docs: list[Document],
    out_dir: Path,
    stamp: str,
    log_fn: Callable[[str], None] = print,
) -> int:
    """Скачать содержание для строк выгрузки. Возвращает число сохранённых файлов."""
    from .sources import REGISTRY

    content_root = out_dir / f"npa_{stamp}_content"
    saved = 0
    for i, doc in enumerate(docs, start=1):
        slug = SOURCE_SLUG.get(doc.source)
        fetch = getattr(REGISTRY.get(slug), "fetch_content", None) if slug else None
        if not fetch:
            continue
        folder = doc_folder(content_root, doc)
        try:
            path = fetch(doc, folder)
        except Exception as exc:  # noqa: BLE001 — сбой карточки не рушит выгрузку
            log.warning("содержание %s %s: %s", doc.source, doc.number, exc)
            log_fn(f"  содержание {doc.source} {doc.number}: пропуск ({exc})")
            continue
        if path is None:
            continue
        doc.content_path = relative_to_out(path, out_dir)
        saved += 1
        if i % 10 == 0 or i == len(docs):
            log_fn(f"  содержание: {i}/{len(docs)}")
    return saved
