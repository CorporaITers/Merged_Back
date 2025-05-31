#!/bin/bash

echo "Starting Azure App Service deployment setup for PO Management System..."

# システムパッケージの更新
echo "Updating package lists..."
apt-get update

# Tesseract OCRのインストール
echo "Installing Tesseract OCR..."
apt-get install -y tesseract-ocr tesseract-ocr-jpn tesseract-ocr-eng

# PDF処理用ライブラリのインストール
echo "Installing Poppler utilities..."
apt-get install -y poppler-utils

# 画像処理用ライブラリのインストール
echo "Installing image processing libraries..."
apt-get install -y libjpeg-dev libpng-dev

# 現行システムで使用される一時ディレクトリの作成
echo "Setting up temporary directories..."
mkdir -p /tmp/po_uploads
chmod 755 /tmp/po_uploads

# Azure MySQL用SSL証明書ディレクトリの作成
echo "Setting up SSL certificate directory..."
mkdir -p /opt/ssl

# Azure MySQL SSL証明書のダウンロード（必要に応じて）
if [ ! -f "/opt/ssl/BaltimoreCyberTrustRoot.crt.pem" ]; then
    echo "Downloading Azure MySQL SSL certificate..."
    wget -O /opt/ssl/BaltimoreCyberTrustRoot.crt.pem https://www.digicert.com/CACerts/BaltimoreCyberTrustRoot.crt.pem
    chmod 644 /opt/ssl/BaltimoreCyberTrustRoot.crt.pem
fi

# Python依存関係のインストール
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Tesseractの動作確認
echo "Testing Tesseract installation..."
tesseract --version

echo "System setup completed successfully."

# 現行システムのPythonアプリケーション起動
echo "Starting PO Management System..."
cd /home/site/wwwroot
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
