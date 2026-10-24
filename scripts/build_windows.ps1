$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$Python = if ($env:PYTHON) { $env:PYTHON } else { Join-Path $Root ".venv\Scripts\python.exe" }
$ModelsDir = "src\ezyocr\resources\models"
$AppDir = "build\ezyocr\windows\app"

function Invoke-Step {
    param([string[]]$Command)
    & $Command[0] $Command[1..($Command.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $($Command -join ' ')"
    }
}

if (-not (Test-Path $Python)) {
    Write-Host "==> Creating virtual environment"
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Invoke-Step @("uv", "venv", "--python", "3.12", ".venv")
        Invoke-Step @("uv", "pip", "install", "--python", $Python, "-e", ".[dev]")
    } else {
        Invoke-Step @("py", "-3.12", "-m", "venv", ".venv")
        Invoke-Step @($Python, "-m", "pip", "install", "--upgrade", "pip")
        Invoke-Step @($Python, "-m", "pip", "install", "-e", ".[dev]")
    }
}

if (-not (Get-ChildItem -Path $ModelsDir -Directory -ErrorAction SilentlyContinue)) {
    Write-Host "==> Downloading OCR models"
    Invoke-Step @($Python, "scripts\fetch_models.py")
}

if (-not (Test-Path "packaging\icons\ezyocr.ico")) {
    Write-Host "==> Generating app icon"
    Invoke-Step @($Python, "scripts\make_icon.py")
}

$PyprojectStamp = Join-Path $AppDir ".pyproject.toml"
if ((Test-Path $AppDir) -and (-not (Test-Path $PyprojectStamp) -or (Get-FileHash "pyproject.toml").Hash -ne (Get-FileHash $PyprojectStamp).Hash)) {
    Write-Host "==> pyproject.toml changed, recreating app"
    Remove-Item -Recurse -Force $AppDir
}

if (Test-Path $AppDir) {
    Write-Host "==> Updating app"
    Invoke-Step @($Python, "-m", "briefcase", "update", "windows", "app", "--update-requirements", "--update-resources", "--no-input")
} else {
    Write-Host "==> Creating app"
    Invoke-Step @($Python, "-m", "briefcase", "create", "windows", "app", "--no-input")
    Copy-Item "pyproject.toml" $PyprojectStamp
}

Write-Host "==> Building app"
Invoke-Step @($Python, "-m", "briefcase", "build", "windows", "app", "--no-input")

Write-Host "==> Packaging MSI"
if ($env:SIGN_IDENTITY) {
    Invoke-Step @($Python, "-m", "briefcase", "package", "windows", "app", "--identity", $env:SIGN_IDENTITY, "--no-input")
} else {
    Invoke-Step @($Python, "-m", "briefcase", "package", "windows", "app", "--adhoc-sign", "--no-input")
}

Write-Host "==> Done:"
Get-ChildItem dist\*.msi | ForEach-Object { $_.FullName }
