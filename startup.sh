#!/bin/bash

# Tesseractのインストール（Ubuntu/Debian系）
echo "Installing Tesseract OCR..."
apt-get update
apt-get install -y tesseract-ocr tesseract-ocr-jpn tesseract-ocr-eng

# Popper（PDF処理用）のインストール
apt-get install -y poppler-utils

# Pythonアプリケーションの起動
echo "Starting Python application..."
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
