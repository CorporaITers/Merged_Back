# init_db.py
import logging
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from database import SessionLocal, engine
import models
from auth import get_password_hash
import config

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    """
    データベースの初期化処理
    - テーブルの作成
    - 初期ユーザーの作成
    """
    # モデルからテーブルを作成
    models.Base.metadata.create_all(bind=engine)
    logger.info("データベーステーブルを作成しました")
    
    # 初期ユーザーの作成
    create_initial_users()

def create_initial_users():
    """
    初期ユーザーの作成
    """
    db = SessionLocal()
    try:
        # 管理者ユーザーの作成（既に存在しない場合）
        admin_user = db.query(models.User).filter(models.User.email == "admin@example.com").first()
        if not admin_user:
            hashed_password = get_password_hash("admin123")  # 本番環境では強力なパスワードに変更
            admin_user = models.User(
                name="管理者",
                email="admin@example.com",
                password_hash=hashed_password,
                role="admin"
            )
            db.add(admin_user)
            logger.info("管理者ユーザーを作成しました")
        
        # 開発用ユーザーの作成（開発モードの場合）
        if config.DEV_MODE:
            dev_user = db.query(models.User).filter(models.User.email == "dev@example.com").first()
            if not dev_user:
                hashed_password = get_password_hash("devpass")
                dev_user = models.User(
                    name="開発ユーザー",
                    email="dev@example.com",
                    password_hash=hashed_password,
                    role="admin"
                )
                db.add(dev_user)
                logger.info("開発用ユーザーを作成しました")
        
        db.commit()
        logger.info("初期ユーザーの作成が完了しました")
    
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"初期ユーザー作成中にエラーが発生しました: {e}")
    
    finally:
        db.close()

def create_test_data():
    """
    テスト用データの作成（開発環境用）
    """
    if not config.DEV_MODE:
        logger.info("開発モードでないため、テストデータは作成しません")
        return
    
    db = SessionLocal()
    try:
        # 開発ユーザーのIDを取得
        dev_user = db.query(models.User).filter(models.User.email == "dev@example.com").first()
        if not dev_user:
            logger.error("開発ユーザーが見つかりません。先に init_db() を実行してください")
            return
        
        # テスト用POを作成（既に存在しない場合）
        existing_po = db.query(models.PurchaseOrder).filter(
            models.PurchaseOrder.po_number == "PO-TEST-001"
        ).first()
        
        if not existing_po:
            # POデータ作成
            test_po = models.PurchaseOrder(
                user_id=dev_user.id,
                customer_name="テスト顧客",
                po_number="PO-TEST-001",
                currency="JPY",
                total_amount="1,000,000",
                payment_terms="30日以内",
                shipping_terms="CIF",
                destination="東京",
                status="手配中"
            )
            db.add(test_po)
            db.flush()  # IDを取得するため
            
            # 製品データ
            test_product = models.OrderItem(
                po_id=test_po.id,
                product_name="テスト製品",
                quantity="100",
                unit_price="10,000",
                subtotal="1,000,000"
            )
            db.add(test_product)
            
            # 追加情報
            test_input = models.Input(
                po_id=test_po.id,
                shipment_arrangement="完了",
                po_acquisition_date="2023-01-15",
                organization="営業部",
                memo="テスト用データです"
            )
            db.add(test_input)
            
            db.commit()
            logger.info("テストデータを作成しました")
        else:
            logger.info("テストデータは既に存在します")
    
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"テストデータ作成中にエラーが発生しました: {e}")
    
    finally:
        db.close()

if __name__ == "__main__":
    logger.info("データベース初期化を開始します...")
    init_db()
    
    logger.info("テストデータ作成を開始します...")
    create_test_data()
    
    logger.info("データベース初期化が完了しました")