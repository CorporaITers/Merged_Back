# startup.sh - Azure App Service 権限制限対応版
#!/bin/bash

echo "🚀 Starting Azure App Service deployment setup for PO Management System..."

# 現在のユーザーと権限を確認
echo "Current user: $(whoami)"
echo "Current directory: $(pwd)"
echo "HOME directory: $HOME"

# 権限が必要なパッケージインストールをスキップし、代替手段を使用
echo "📦 Setting up alternative OCR dependencies..."

# 一時ディレクトリの作成（権限のある場所に）
echo "📁 Setting up temporary directories..."
mkdir -p /tmp/po_uploads
mkdir -p /home/site/wwwroot/temp
chmod 755 /tmp/po_uploads 2>/dev/null || true
chmod 755 /home/site/wwwroot/temp 2>/dev/null || true

# SSL証明書ディレクトリの作成（権限のある場所に）
echo "🔐 Setting up SSL certificate directory..."
mkdir -p /home/site/wwwroot/ssl
cd /home/site/wwwroot/ssl

# Azure MySQL SSL証明書のダウンロード（権限のある場所に）
if [ ! -f "/home/site/wwwroot/ssl/BaltimoreCyberTrustRoot.crt.pem" ]; then
    echo "📥 Downloading Azure MySQL SSL certificate..."
    wget -O /home/site/wwwroot/ssl/BaltimoreCyberTrustRoot.crt.pem https://www.digicert.com/CACerts/BaltimoreCyberTrustRoot.crt.pem 2>/dev/null || true
    chmod 644 /home/site/wwwroot/ssl/BaltimoreCyberTrustRoot.crt.pem 2>/dev/null || true
fi

# Python環境の確認
echo "🐍 Python environment check..."
python3 --version
pip --version

# 現在のディレクトリに移動
cd /home/site/wwwroot

# Python依存関係の再インストール（念のため）
echo "📦 Installing Python dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# Tesseractの代替確認
echo "🔍 Checking OCR capabilities..."
python3 -c "
try:
    import pytesseract
    print('✅ pytesseract imported successfully')
    try:
        version = pytesseract.get_tesseract_version()
        print(f'✅ Tesseract version: {version}')
    except Exception as e:
        print(f'⚠️  Tesseract binary not found, will use fallback: {e}')
except ImportError as e:
    print(f'❌ pytesseract import failed: {e}')
"

# PDF処理ライブラリの確認
echo "📄 Checking PDF processing capabilities..."
python3 -c "
try:
    import pdf2image
    print('✅ pdf2image imported successfully')
except ImportError as e:
    print(f'❌ pdf2image import failed: {e}')

try:
    import camelot
    print('✅ camelot imported successfully')
except ImportError as e:
    print(f'❌ camelot import failed: {e}')
"

# アプリケーション構造の確認
echo "📂 Checking application structure..."
ls -la /home/site/wwwroot/
if [ -f "/home/site/wwwroot/main.py" ]; then
    echo "✅ main.py found in root"
elif [ -f "/home/site/wwwroot/app/main.py" ]; then
    echo "✅ main.py found in app directory"
else
    echo "❌ main.py not found"
fi

# 環境変数の設定
echo "🔧 Setting up environment variables..."
export PYTHONPATH="/home/site/wwwroot:$PYTHONPATH"
export OCR_TEMP_FOLDER="/tmp/po_uploads"
export UPLOAD_FOLDER="/tmp/po_uploads"
export SSL_CERT_PATH="/home/site/wwwroot/ssl/BaltimoreCyberTrustRoot.crt.pem"

echo "✅ Environment setup completed."
echo "🚀 Starting PO Management System..."

# アプリケーションの起動
if [ -f "/home/site/wwwroot/main.py" ]; then
    echo "Starting from root directory..."
    python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
elif [ -f "/home/site/wwwroot/app/main.py" ]; then
    echo "Starting from app module..."
    python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
else
    echo "❌ Could not find main.py, attempting default startup..."
    python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
fi