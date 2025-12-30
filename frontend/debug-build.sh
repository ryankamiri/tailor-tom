#!/bin/bash
set -e

echo "=== Current Directory ==="
pwd

echo "=== Root Directory Contents ==="
ls -la ../

echo "=== Frontend Directory Contents ==="
ls -la .

echo "=== App Directory Contents ==="
ls -la app/ || echo "app/ not found"

echo "=== Lib Directory Contents ==="
ls -la lib/ || echo "lib/ not found"

echo "=== Starting Build ==="
npm run build

