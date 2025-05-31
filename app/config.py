# config.py - Azure App Service 対応版（権限制限対応）
import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv
import subprocess

# .env ファイルをロード
BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / '.env'
load_dotenv(dotenv_path=env_path)

# データベース接続情報
DB_HOST = os.getenv("DB_HOST", "tech0-gen-8-step4-dtx-db.mysql.database.azure.com")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "ryoueno")
DB_PASSWORD = os.getenv("DB_PASSWORD", "tech0-dtxdb")
DB_NAME = os.getenv("DB_NAME", "corporaiters")

# SSL 設定
DB_SSL_REQUIRED = True

# JWT 認証設定
SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key_should_be_at_least_32_characters")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

# Azure App Service対応 - 権限のある場所を使用
def get_writable_temp_dir():
    """書き込み可能な一時ディレクトリを取得"""
    candidates = [
        os.getenv("OCR_TEMP_FOLDER"),
        os.getenv("UPLOAD_FOLDER"),
        "/tmp/po_uploads",
        "/home/site/wwwroot/temp",
        tempfile.gettempdir(),
        "/tmp"
    ]
    
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            try:
                # 書き込みテスト
                test_file = os.path.join(candidate, "test_write.tmp")
                with open(test_file, 'w') as f:
                    f.write("test")
                os.unlink(test_file)
                return candidate
            except (OSError, PermissionError):
                continue
    
    # フォールバック: システムの一時ディレクトリ
    return tempfile.gettempdir()

# アプリケーション設定
UPLOAD_FOLDER = get_writable_temp_dir()
OCR_TEMP_FOLDER = UPLOAD_FOLDER

# OCR設定（権限制限対応）
def get_tesseract_path():
    """Tesseractの実行パスを取得"""
    candidates = [
        os.getenv("TESSERACT_CMD"),
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/opt/homebrew/bin/tesseract",  # macOS
        "tesseract"  # PATH内検索
    ]
    
    for candidate in candidates:
        if candidate:
            try:
                result = subprocess.run([candidate, "--version"], 
                                     capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    return candidate
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                continue
    
    return "tesseract"  # デフォルト

TESSERACT_CMD = get_tesseract_path()
TEMP_DIR = OCR_TEMP_FOLDER

# SSL証明書パス（権限のある場所）
SSL_CERT_CANDIDATES = [
    os.getenv("SSL_CERT_PATH"),
    "/home/site/wwwroot/ssl/BaltimoreCyberTrustRoot.crt.pem",
    "/opt/ssl/BaltimoreCyberTrustRoot.crt.pem",
    None
]

SSL_CERT_PATH = None
for cert_path in SSL_CERT_CANDIDATES:
    if cert_path and os.path.exists(cert_path):
        SSL_CERT_PATH = cert_path
        break

# ファイルアップロード設定
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "10485760"))  # 10MB
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

# 開発モード設定
DEV_MODE = os.getenv("DEV_MODE", "False").lower() in ("true", "1", "t")

# 必要なディレクトリを作成
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(OCR_TEMP_FOLDER, exist_ok=True)
except OSError:
    pass  # 権限エラーは無視

# データベース接続URL（SSL設定対応）
if DB_SSL_REQUIRED:
    if SSL_CERT_PATH:
        # SSL証明書が利用可能な場合
        DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?ssl_ca={SSL_CERT_PATH}&ssl_verify_cert=true&ssl_verify_identity=true"
    else:
        # SSL証明書が見つからない場合はシンプルなSSL接続
        DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?ssl=true&ssl_check_hostname=false&ssl_verify_mode=CERT_NONE"
else:
    DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ログ設定
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Azure環境判定
IS_AZURE = os.getenv("WEBSITE_SITE_NAME") is not None

# デバッグ情報（開発時のみ）
if DEV_MODE:
    print(f"[CONFIG] Upload folder: {UPLOAD_FOLDER}")
    print(f"[CONFIG] OCR temp folder: {OCR_TEMP_FOLDER}")
    print(f"[CONFIG] Tesseract path: {TESSERACT_CMD}")
    print(f"[CONFIG] SSL cert path: {SSL_CERT_PATH}")
    print(f"[CONFIG] Is Azure: {IS_AZURE}")
    print(f"[CONFIG] Database URL: {DATABASE_URL[:50]}...")