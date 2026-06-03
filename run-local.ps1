$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeRoot = "D:\prop-firm-ai-runtime"
$venvRoot = Join-Path $runtimeRoot ".venv"
Set-Location $projectRoot

New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null

if (-not (Test-Path $venvRoot)) {
    python -m venv $venvRoot
}

$python = Join-Path $venvRoot "Scripts\python.exe"
$pip = Join-Path $venvRoot "Scripts\pip.exe"

& $pip install -e .[dev]

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

$env:OLLAMA_MODELS = "D:\Ollama\models"
New-Item -ItemType Directory -Force -Path $env:OLLAMA_MODELS | Out-Null

Write-Host "Checking local Ollama..." -ForegroundColor Cyan
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -Method Get -TimeoutSec 5
    $model = (Get-Content ".env" | Where-Object { $_ -match "^OLLAMA_CATALYST_MODEL=" } | Select-Object -First 1).Split("=")[1]
    $installed = @($health.models | ForEach-Object { $_.name })
    if ($installed -notcontains $model) {
        Write-Host "Model $model is not installed. Run: ollama pull $model" -ForegroundColor Yellow
    }
} catch {
    Write-Host "Ollama is not running on this PC. Start it with: ollama serve" -ForegroundColor Yellow
}

Write-Host "Starting local app on http://127.0.0.1:8000/app/" -ForegroundColor Green
& $python -m uvicorn prop_firm_ai.main:app --host 127.0.0.1 --port 8000 --reload
