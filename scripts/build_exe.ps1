$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    $Py = "python"
}

Write-Host "Python: $Py"
& $Py -m pip install -r requirements.txt -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Py -m PyInstaller --noconfirm --clean npa-monitor.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Copy-Item -Force (Join-Path $Root "config.yaml") (Join-Path $Root "dist\config.yaml")
Copy-Item -Force (Join-Path $Root ".env.example") (Join-Path $Root "dist\.env.example")

$Exe = Join-Path $Root "dist\npa-monitor.exe"
Write-Host "Done: $Exe"
Write-Host "The exe has built-in defaults. Optional config.yaml / .env next to it override them."
