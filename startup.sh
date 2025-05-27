#!/bin/bash

# システムライブラリのインストール (必要に応じて)
apt-get update
apt-get install -y poppler-utils tesseract-ocr

# アプリケーション起動
gunicorn app:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 120
