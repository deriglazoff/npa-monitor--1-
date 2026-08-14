# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)

a = Analysis(
    [str(root / "src" / "npa_monitor" / "gui.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[
        (str(root / "config.yaml"), "."),
        (str(root / ".env.example"), "."),
    ],
    hiddenimports=[
        "bs4",
        "dotenv",
        "lxml",
        "lxml._elementpath",
        "lxml.etree",
        "npa_monitor",
        "npa_monitor.content",
        "npa_monitor.export",
        "npa_monitor.filters",
        "npa_monitor.gui",
        "npa_monitor.http",
        "npa_monitor.models",
        "npa_monitor.paths",
        "npa_monitor.runner",
        "npa_monitor.sources",
        "npa_monitor.sources.cbr",
        "npa_monitor.sources.regulation",
        "npa_monitor.sources.sozd",
        "openpyxl",
        "requests",
        "yaml",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="npa-monitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
