# PowerShell Setup Script for LifeThread Monorepo
$ErrorActionPreference = "Stop"

Write-Host "=== Initializing LifeThread Monorepo ===" -ForegroundColor Cyan

if (-not (Test-Path ".env")) {
    Write-Host "Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
}

Write-Host "Installing Python packages..." -ForegroundColor Yellow
python -m pip install -e ./backend
python -m pip install -e ./agent
python -m pip install -e ./mcp-server

Write-Host "Installing Frontend dependencies..." -ForegroundColor Yellow
Push-Location frontend
npm install
Pop-Location

Write-Host "Verifying environment configuration..." -ForegroundColor Yellow
python scripts/verify_env.py

Write-Host "=== LifeThread Setup Complete ===" -ForegroundColor Green
