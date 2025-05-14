# config.py
import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv

# .env ファイルをロード
# プロジェクトルートにある .env ファイルを読み込む
BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / '.env'
load_dotenv(dotenv_path=env_path)

# データベース接続情報
DB_HOST = os.getenv("DB_HOST", "tech0-gen-8-step4-dtx-db.mysql.database.azure.com")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "ryoueno")
DB_PASSWORD = os.getenv("DB_PASSWORD", "tech0-dtxdb")  # 環境変数で設定
DB_NAME = os.getenv("DB_NAME", "corporaiters")

# SSL 設定が必要
DB_SSL_REQUIRED = True

# JWT 認証設定
SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key_should_be_at_least_32_characters")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

# アプリケーション設定 - 一時ディレクトリを動的に取得
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", tempfile.gettempdir())
OCR_TEMP_FOLDER = os.getenv("OCR_TEMP_FOLDER", tempfile.gettempdir())

# 開発モード設定
DEV_MODE = os.getenv("DEV_MODE", "True").lower() in ("true", "1", "t")

# アップロードフォルダが存在しない場合は作成
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OCR_TEMP_FOLDER, exist_ok=True)

# データベース接続URL（SQLAlchemy形式）
# MySQL+mysqlconnectorの形式を使用してAzure MySQL接続
if DB_SSL_REQUIRED:
    DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?ssl=true"
else:
    DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
