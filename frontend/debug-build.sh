#!/bin/bash
set -e

echo "=== Current Directory ==="
pwd

echo "=== Current Directory Contents ==="
ls -la

echo "=== Parent Directory Contents ==="
ls -la ../ || echo "Cannot access parent directory"

echo "=== App Directory Contents ==="
ls -la app/ || echo "app/ not found"

echo "=== Lib Directory Contents ==="
ls -la lib/ || echo "lib/ not found"

echo "=== Checking lib/api.ts ==="
if [ -f "lib/api.ts" ]; then
  echo "lib/api.ts EXISTS"
  head -5 lib/api.ts
else
  echo "lib/api.ts NOT FOUND"
fi

echo "=== Starting Build ==="
npm run build

