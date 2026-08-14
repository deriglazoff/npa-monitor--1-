"""Корень приложения: исходники vs замороженный .exe.

Настройки: встроенные дефолты (и копия config.yaml внутри exe).
Файл рядом с программой, если есть, перекрывает их.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

RUNTIME_FILES = ("config.yaml", ".env.example")

# Маршруты для запуска из РФ: прокси не нужен. Файл .env рядом с exe перекрывает.
DEFAULT_ENV = {
    "SOZD_ROUTE": "direct",
    "CBR_ROUTE": "direct",
    "REGULATION_ROUTE": "direct",
    "HTTP_TIMEOUT": "45",
    "REQUEST_DELAY": "1.0",
    "MAX_RETRIES": "3",
}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Каталог, из которого читаем .env / config.yaml и куда пишем out/.

    Рядом с .exe — каталог самого exe; при запуске из исходников — корень репозитория.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def bundle_dir() -> Path:
    """Откуда брать встроенные шаблоны: распаковка PyInstaller или корень репозитория."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return app_root()


def ensure_runtime_files() -> None:
    """По возможности положить config.yaml и .env.example рядом с exe — чтобы их было чем править.

    Если каталог только для чтения, приложение всё равно работает со встроенной копией.
    """
    root = app_root()
    bundle = bundle_dir()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for name in RUNTIME_FILES:
        dest = root / name
        src = bundle / name
        if dest.exists() or not src.exists():
            continue
        try:
            shutil.copy2(src, dest)
        except OSError:
            pass


def load_runtime_env() -> None:
    """Порядок: переменные окружения → .env рядом с программой → встроенные дефолты."""
    env_path = app_root() / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)
    for key, value in DEFAULT_ENV.items():
        os.environ.setdefault(key, value)


def resolve_config_file(explicit: Path | None = None) -> Path:
    """config.yaml рядом с программой, иначе встроенный из exe."""
    if explicit is not None:
        path = Path(explicit)
        if path.is_file():
            return path
        default = app_root() / "config.yaml"
        try:
            is_default = path.resolve() == default.resolve()
        except OSError:
            is_default = False
        if not is_default:
            raise FileNotFoundError(f"Файл настроек не найден: {path}")

    nearby = app_root() / "config.yaml"
    if nearby.is_file():
        return nearby
    bundled = bundle_dir() / "config.yaml"
    if bundled.is_file():
        return bundled
    raise FileNotFoundError(
        "Нет config.yaml рядом с программой и нет встроенной копии в приложении"
    )
