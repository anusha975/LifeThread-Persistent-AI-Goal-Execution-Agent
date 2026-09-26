#!/usr/bin/env bash
set -e

echo "=== Initializing LifeThread Monorepo ==="

if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

echo "Installing Python packages..."
pip install -e ./backend
pip install -e ./agent
pip install -e ./mcp-server

echo "Installing Frontend dependencies..."
cd frontend
npm install
cd ..

echo "Verifying environment configuration..."
python scripts/verify_env.py

echo "=== LifeThread Setup Complete ==="
