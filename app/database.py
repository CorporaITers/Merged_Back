# database.py
from sqlalchemy import create_engine, Text, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
import pymysql

# 設定ファイルから接続URL等を読み込む
from app.config import DATABASE_URL

# SQLAlchemyエンジン作成
# Azure MySQLへの接続時のパフォーマンス最適化パラメータを追加
engine = create_engine(
    DATABASE_URL,
    pool_size=10,              # コネクションプールサイズ
    max_overflow=20,           # 最大オーバーフロー接続数
    pool_timeout=30,           # コネクション獲得待機時間（秒）
    pool_recycle=1800,         # 接続リサイクル時間（秒）- MySQLのwait_timeout未満に設定
    pool_pre_ping=True,        # 接続前に接続テスト実行
    connect_args={
        "ssl": {"ssl_mode": "required"}  # SSL接続を強制
    },
    poolclass=QueuePool       # プール管理クラス
)

# セッションローカルとベースの設定
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 依存性注入のためのセッション取得関数
def get_db():
    """
    FastAPIの依存性注入で使用するデータベースセッション取得関数
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# データベース接続テスト関数
def test_db_connection():
    """
    データベース接続をテストする関数
    正常に接続できれば True を返し、エラーの場合は例外を発生させる
    """
    try:
        db = SessionLocal()
        # 単純な接続テストクエリ
        result = db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception as e:
        print(f"データベース接続エラー: {e}")
        raise