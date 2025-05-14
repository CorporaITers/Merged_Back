# app_router.py
from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Form, BackgroundTasks, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session
from typing import List, Optional
import os
import shutil
import uuid
import json
from datetime import datetime, timedelta
import re
import logging
import tempfile

from app.database import SessionLocal, engine, test_db_connection
from app import models

from fastapi import APIRouter
router = APIRouter()


from app import schemas
from app.auth import create_access_token, get_password_hash, verify_password, get_current_user
from app.ocr_service import process_document, extract_po_data
from app import config



# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log")
    ]
)
logger = logging.getLogger(__name__)

# データベース接続テスト
try:
    test_db_connection()
    logger.info("データベース接続成功")
except Exception as e:
    logger.error(f"データベース接続エラー: {e}")



# アップロードディレクトリの作成
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)

# 依存関係
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 認証関連のエンドポイント
@router.post("/api/auth/login", response_model=schemas.Token)
def login(user_data: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == user_data.email).first()
    if not user or not verify_password(user_data.password, user.password_hash):
        logger.warning(f"ログイン失敗: {user_data.email}")
        raise HTTPException(
            status_code=401,
            detail="メールアドレスまたはパスワードが正しくありません",
        )
    
    access_token = create_access_token(
        data={"sub": user.email}
    )
    logger.info(f"ログイン成功: {user_data.email}")
    return {"token": access_token, "token_type": "bearer"}

@router.post("/api/auth/register", response_model=schemas.User)
def register_user(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    # メールアドレスの重複チェック
    db_user = db.query(models.User).filter(models.User.email == user_data.email).first()
    if db_user:
        logger.warning(f"ユーザー登録失敗（メールアドレス重複）: {user_data.email}")
        raise HTTPException(
            status_code=400,
            detail="このメールアドレスは既に登録されています",
        )
    
    # ユーザー作成
    hashed_password = get_password_hash(user_data.password)
    db_user = models.User(
        name=user_data.name,
        email=user_data.email,
        password_hash=hashed_password,
        role=user_data.role
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    logger.info(f"ユーザー登録成功: {user_data.email}")
    return db_user

# OCR関連のエンドポイント
@router.post("/api/ocr/upload")
async def upload_document(
    file: UploadFile = File(...),
    local_kw: Optional[str] = Query(None),  # local_kwクエリパラメータを追加
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,  # リクエストオブジェクトを追加
):
    logger.info(f"Request query params: {request.query_params if request else 'N/A'}")
    logger.info(f"Received file upload request: {file.filename}")
    
    try:
        # ファイル拡張子の確認
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in ['.pdf', '.png', '.jpg', '.jpeg']:
            logger.warning(f"サポートされていないファイル形式: {file_ext}")
            return JSONResponse(
                status_code=400, 
                content={"message": "サポートされていないファイル形式です。PDF, PNG, JPG, JPEGのみがサポートされています。"}
            )
        
        # ユニークなファイル名生成
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        file_location = os.path.join(config.UPLOAD_FOLDER, unique_filename)
        
        logger.info(f"Saving file to: {file_location}")
        
        # ファイルの内容を読み取り
        file_content = await file.read()

        # ファイルを保存
        with open(file_location, "wb") as buffer:
            buffer.write(file_content)
        
        # OCR結果レコード作成 - raw_textに整数値を設定
        ocr_result = models.OCRResult(
            status="processing",
            raw_text=0,  # 整数値として0を保存
            processed_data=json.dumps({"file_path": file_location, "original_filename": file.filename}),
            ocrresultscol1="default_value"  # ocrresultscol1フィールドを追加
        )
        db.add(ocr_result)
        db.commit()
        db.refresh(ocr_result)
        
        # ログを記録（ファイルアップロードのアクション）
        log_entry = models.Log(
            user_id=current_user.user_id,
            action="ファイルアップロード",
            processed_data=json.dumps({"file_name": file.filename, "ocr_id": ocr_result.ocr_id})
        )
        db.add(log_entry)
        db.commit()
        
        logger.info(f"Created OCR result record with ID: {ocr_result.ocr_id}")
        
        # バックグラウンドでOCR処理
        if background_tasks:
            background_tasks.add_task(
                process_document,
                file_path=file_location,  # ファイルパスは直接関数に渡す
                ocr_id=ocr_result.ocr_id,
                db=db
            )
            logger.info(f"Added background task for OCR processing with file: {file_location}")
        else:
            # 開発環境用: OCRをスキップして直接完了状態にする
            logger.info("No background tasks available, setting result to completed")
            ocr_result.status = "completed"
            ocr_result.raw_text = 0
            ocr_result.processed_data = json.dumps({
                "file_path": file_location,
                "text_content": "Sample OCR text for development"
            })
            db.commit()
        
        return {
            "ocrId": str(ocr_result.ocr_id), 
            "status": "processing"
        }

    except Exception as e:
        logger.error(f"Error during file upload: {str(e)}")
        return JSONResponse(
            status_code=500, 
            content={"message": f"ファイルのアップロードに失敗しました: {str(e)}"}
        )

@router.get("/api/ocr/status/{ocr_id}")
async def get_ocr_status(
    ocr_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    ocr_result = db.query(models.OCRResult).filter(models.OCRResult.ocr_id == ocr_id).first()
    if not ocr_result:
        logger.warning(f"OCR結果が見つかりません: ID={ocr_id}")
        raise HTTPException(status_code=404, detail="指定されたOCR結果が見つかりません")
    
    logger.info(f"OCRステータス取得: ID={ocr_id}, ステータス={ocr_result.status}")
    return {"ocrId": ocr_result.ocr_id, "status": ocr_result.status}

@router.get("/api/ocr/extract/{ocr_id}")
async def extract_order_data(
    ocr_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    ocr_result = db.query(models.OCRResult).filter(models.OCRResult.ocr_id == ocr_id).first()
    if not ocr_result:
        logger.warning(f"OCR結果が見つかりません: ID={ocr_id}")
        raise HTTPException(status_code=404, detail="指定されたOCR結果が見つかりません")
    
    if ocr_result.status != "completed":
        logger.warning(f"OCR処理が完了していません: ID={ocr_id}, ステータス={ocr_result.status}")
        raise HTTPException(status_code=400, detail="OCR処理がまだ完了していません")
    
    # 発注書データの抽出
    # OCR IDを渡して、extract_po_data関数でテキスト内容を取得
    extracted_data = extract_po_data(ocr_id)
    
    logger.info(f"OCRデータ抽出: ID={ocr_id}")
    return {"ocrId": ocr_result.ocr_id, "data": extracted_data}

# PO関連のエンドポイント
@router.post("/api/po/register")
async def register_po(
    po_data: schemas.POCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        # POの作成
        po = models.PurchaseOrder(
            user_id=current_user.user_id,
            customer_name=po_data.customer,
            po_number=po_data.poNumber,
            currency=po_data.currency,
            total_amount=po_data.totalAmount,
            payment_terms=po_data.paymentTerms,
            shipping_terms=po_data.terms,
            destination=po_data.destination,
            status="手配前"  # デフォルトステータス
        )
        db.add(po)
        db.commit()
        db.refresh(po)
        
        # 製品の登録
        for product in po_data.products:
            order_item = models.OrderItem(
                po_id=po.po_id,  # po_idに変更
                product_name=product.name,  # フィールド名を修正
                quantity=product.quantity,
                unit_price=product.unitPrice,  # フィールド名を修正
                subtotal=product.amount  # フィールド名を修正
            )
            db.add(order_item)
        
        db.commit()
        
        # PO登録のログ記録
        log_entry = models.Log(
            user_id=current_user.user_id,
            action="PO登録",
            processed_data=json.dumps({"po_id": po.po_id, "po_number": po_data.poNumber, "customer": po_data.customer})
        )
        db.add(log_entry)
        db.commit()
        
        logger.info(f"PO登録完了: ID={po.po_id}, PO番号={po_data.poNumber}, 顧客={po_data.customer}")
        return {"success": True, "poId": po.po_id}
    
    except Exception as e:
        logger.error(f"PO登録エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=f"POの登録に失敗しました: {str(e)}")

# POの一覧取得
@router.get("/api/po/list")
async def get_po_list(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        # POの一覧取得
        po_list = db.query(models.PurchaseOrder).all()
        
        result = []
        for po in po_list:
            # 製品情報の取得
            items = db.query(models.OrderItem).filter(models.OrderItem.po_id == po.po_id).all()
            
            # 追加情報の取得
            input_info = db.query(models.Input).filter(models.Input.po_id == po.po_id).first()
            shipping_info = db.query(models.ShippingSchedule).filter(models.ShippingSchedule.po_id == po.po_id).first()
            
            # 製品名の結合
            product_names = ", ".join([item.product_name for item in items])
            
            # 数量の計算（エラー処理を追加）
            total_quantity = 0
            if items:
                for item in items:
                    try:
                        # カンマを除去して数値に変換
                        quantity_str = item.quantity or "0"
                        if isinstance(quantity_str, str):
                            quantity_str = quantity_str.replace(',', '')
                        quantity_value = float(quantity_str)
                        total_quantity += quantity_value
                    except (ValueError, TypeError):
                        # 変換できない場合は0として扱う
                        logger.warning(f"数量変換エラー: '{item.quantity}'を数値に変換できません。ID={po.po_id}")
            
            # 結果の作成
            po_info = {
                "id": po.po_id,  
                "status": po.status,
                "acquisitionDate": input_info.po_acquisition_date if input_info else None,
                "organization": input_info.organization if input_info else None,
                "invoice": "完了" if input_info and input_info.invoice_number else "",
                "payment": "完了" if input_info and input_info.payment_status == "completed" else "",
                "booking": "完了" if shipping_info else "",
                "manager": current_user.name,
                "invoiceNumber": input_info.invoice_number if input_info else None,
                "poNumber": po.po_number,
                "customer": po.customer_name,
                "productName": product_names,
                "quantity": total_quantity,  
                "currency": po.currency,
                "unitPrice": items[0].unit_price if items else None,
                "amount": po.total_amount,
                "paymentTerms": po.payment_terms,
                "terms": po.shipping_terms,
                "destination": po.destination,  
                "transitPoint": shipping_info.transit_point if shipping_info else None,
                "cutOffDate": shipping_info.cut_off_date if shipping_info else None,
                "etd": shipping_info.etd if shipping_info else None,
                "eta": shipping_info.eta if shipping_info else None,
                "bookingNumber": shipping_info.booking_number if shipping_info else None,
                "vesselName": shipping_info.vessel_name if shipping_info else None,
                "voyageNumber": shipping_info.voyage_number if shipping_info else None,
                "containerInfo": shipping_info.container_size if shipping_info else None,
                "memo": input_info.memo if input_info else None
            }
            
            result.append(po_info)
        
        # PO一覧取得のログ記録
        log_entry = models.Log(
            user_id=current_user.user_id,
            action="PO一覧取得",
            processed_data=json.dumps({"count": len(result)})
        )
        db.add(log_entry)
        db.commit()
        
        logger.info(f"PO一覧取得: {len(result)}件")
        return {"success": True, "po_list": result}
    
    except Exception as e:
        logger.error(f"PO一覧取得エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=f"PO一覧の取得に失敗しました: {str(e)}")

# PO詳細の製品情報を取得するエンドポイント
@router.get("/api/po/{po_id}/products")
async def get_po_products(
    po_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    特定のPOに関連する製品情報を取得する
    """
    try:
        # POの存在確認
        po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.po_id == po_id).first()
        if not po:
            logger.warning(f"製品情報取得失敗（存在しないPO）: ID={po_id}")
            raise HTTPException(status_code=404, detail="指定されたPOが見つかりません")
        
        # 製品情報を取得
        products = db.query(models.OrderItem).filter(models.OrderItem.po_id == po_id).all()
        
        # 結果の整形
        result = []
        for product in products:
            product_info = {
                "id": product.item_id,  
                "po_id": product.po_id,
                "product_name": product.product_name,
                "quantity": product.quantity,
                "unit_price": product.unit_price,
                "subtotal": product.subtotal
            }
            result.append(product_info)
        
        # 製品情報取得のログ記録
        log_entry = models.Log(
            user_id=current_user.user_id,
            action="製品情報取得",
            processed_data=json.dumps({"po_id": po_id, "product_count": len(result)})
        )
        db.add(log_entry)
        db.commit()
        
        logger.info(f"PO製品情報取得: PO ID={po_id}, 製品数={len(result)}")
        return {"success": True, "products": result}
    
    except HTTPException:
        raise  # HTTPExceptionはそのまま再送出
    except Exception as e:
        logger.error(f"製品情報取得エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=f"製品情報の取得に失敗しました: {str(e)}")

@router.patch("/api/po/{po_id}/status")
async def update_po_status(
    po_id: int,
    status_data: schemas.StatusUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # POの取得
    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.po_id == po_id).first()
    if not po:
        logger.warning(f"PO更新失敗（存在しないPO）: ID={po_id}")
        raise HTTPException(status_code=404, detail="指定されたPOが見つかりません")
    
    # ステータスの更新
    valid_statuses = ["手配前", "手配中", "手配済", "計上済"]
    if status_data.status not in valid_statuses:
        logger.warning(f"PO更新失敗（無効なステータス）: ID={po_id}, ステータス={status_data.status}")
        raise HTTPException(status_code=400, detail="無効なステータスです")
    
    # 計上済みから他のステータスへの変更を禁止
    if po.status == "計上済" and status_data.status != "計上済":
        logger.warning(f"PO更新失敗（計上済みPOの変更）: ID={po_id}")
        raise HTTPException(status_code=400, detail="計上済みのPOのステータスは変更できません")
    
    old_status = po.status
    po.status = status_data.status
    db.commit()
    
    # ステータス更新のログ記録
    log_entry = models.Log(
        user_id=current_user.user_id,
        action="POステータス更新",
        processed_data=json.dumps({"po_id": po_id, "old_status": old_status, "new_status": status_data.status})
    )
    db.add(log_entry)
    db.commit()
    
    logger.info(f"POステータス更新: ID={po_id}, 旧ステータス={old_status}, 新ステータス={status_data.status}")
    return {"success": True, "status": po.status}

@router.put("/api/po/{po_id}/memo")
async def update_po_memo(
    po_id: int,
    memo_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    POのメモを更新するエンドポイント
    """
    try:
        # POの取得
        po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.po_id == po_id).first()
        if not po:
            logger.warning(f"POメモ更新失敗（存在しないPO）: ID={po_id}")
            raise HTTPException(status_code=404, detail="指定されたPOが見つかりません")
        
        # Input情報の取得または作成
        input_info = db.query(models.Input).filter(models.Input.po_id == po_id).first()
        if not input_info:
            # 入力情報がない場合は新規作成
            today_date = datetime.now().strftime("%Y-%m-%d")
            input_info = models.Input(
                po_id=po_id,
                shipment_arrangement="手配前",
                memo=memo_data.get("memo", "　"),
                po_acquisition_date=today_date,
                organization="　",
                payment_status="pending",
                invoice_number="　",  # Noneの文字列を設定
                booking_number="　"   # Noneの文字列を設定
            )
            db.add(input_info)
        else:
            # 既存の入力情報を更新
            input_info.memo = memo_data.get("memo", "")
        
        db.commit()
        
        # メモ更新のログ記録
        log_entry = models.Log(
            user_id=current_user.user_id,
            action="POメモ更新",
            processed_data=json.dumps({"po_id": po_id, "memo": memo_data.get("memo", "")})
        )
        db.add(log_entry)
        db.commit()
        
        logger.info(f"POメモ更新: ID={po_id}")
        return {"success": True, "memo": input_info.memo}
    
    except Exception as e:
        db.rollback()  # エラーが発生した場合はロールバック
        logger.error(f"POメモ更新エラー: {str(e)}")
        raise HTTPException(status_code=500, detail=f"メモの更新に失敗しました: {str(e)}")

@router.post("/api/po/{po_id}/shipping")
async def add_shipping_info(
    po_id: int,
    shipping_data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # POの取得
    po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.po_id == po_id).first()
    if not po:
        logger.warning(f"出荷情報追加失敗（存在しないPO）: ID={po_id}")
        raise HTTPException(status_code=404, detail="指定されたPOが見つかりません")
    
    # すでに出荷情報がある場合は上書き
    shipping_info = db.query(models.ShippingSchedule).filter(models.ShippingSchedule.po_id == po_id).first()
    
    if not shipping_info:
        # 新規作成
        shipping_info = models.ShippingSchedule(
            po_id=po_id,
            shipping_company=shipping_data.get("shipping_company", ""),
            transit_point=shipping_data.get("transit_point", ""),
            cut_off_date=shipping_data.get("cut_off_date", ""),
            etd=shipping_data.get("etd", ""),
            eta=shipping_data.get("eta", ""),
            booking_number=shipping_data.get("booking_number", ""),
            vessel_name=shipping_data.get("vessel_name", ""),
            voyage_number=shipping_data.get("voyage_number", ""),
            container_size=shipping_data.get("container_size", "")
        )
        db.add(shipping_info)
    else:
        # 既存情報の更新
        shipping_info.shipping_company = shipping_data.get("shipping_company", shipping_info.shipping_company)
        shipping_info.transit_point = shipping_data.get("transit_point", shipping_info.transit_point)
        shipping_info.cut_off_date = shipping_data.get("cut_off_date", shipping_info.cut_off_date)
        shipping_info.etd = shipping_data.get("etd", shipping_info.etd)
        shipping_info.eta = shipping_data.get("eta", shipping_info.eta)
        shipping_info.booking_number = shipping_data.get("booking_number", shipping_info.booking_number)
        shipping_info.vessel_name = shipping_data.get("vessel_name", shipping_info.vessel_name)
        shipping_info.voyage_number = shipping_data.get("voyage_number", shipping_info.voyage_number)
        shipping_info.container_size = shipping_data.get("container_size", shipping_info.container_size)
    
    # もし予約番号が設定されたら、ステータスを「手配済」に変更
    if shipping_info.booking_number and po.status == "手配中":
        po.status = "手配済"
    
    db.commit()
    
    # 出荷情報更新のログ記録
    log_entry = models.Log(
        user_id=current_user.user_id,
        action="出荷情報更新",
        processed_data=json.dumps({"po_id": po_id, "booking_number": shipping_info.booking_number})
    )
    db.add(log_entry)
    db.commit()
    
    logger.info(f"出荷情報追加/更新: PO ID={po_id}")
    return {"success": True, "shippingId": shipping_info.id}



# サーバーデバッグ用のエンドポイント
@router.get("/api/debug/status")
async def debug_status():
    """サーバー状態を確認するためのデバッグエンドポイント"""
    return {
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "upload_dir_exists": os.path.exists(config.UPLOAD_FOLDER),
        "env": {
            "dev_mode": config.DEV_MODE,
            "db_host": config.DB_HOST,
            "db_name": config.DB_NAME
        }
    }

# ヘルスチェック用エンドポイント
@router.get("/api/health")
async def health_check():
    """ヘルスチェック用のエンドポイント"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "system_status": {
            "upload_dir": os.path.exists(config.UPLOAD_FOLDER),
            "tmp_dir": os.path.exists(tempfile.gettempdir()),
        }
    }

# 起動時のカスタム処理
@router.on_event("startup")
async def startup_event():
    logger.info("アプリケーション起動")
    logger.info(f"UPLOAD_FOLDER: {config.UPLOAD_FOLDER}")
    logger.info(f"OCR_TEMP_FOLDER: {config.OCR_TEMP_FOLDER}")
    
    # ディレクトリの再作成
    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(config.OCR_TEMP_FOLDER, exist_ok=True)
    
    # 初期データ投入（開発環境のみ）
    if config.DEV_MODE:
        db = SessionLocal()
        try:
            # 開発用ユーザーが存在しない場合は作成
            dev_user = db.query(models.User).filter(models.User.email == "dev@example.com").first()
            if not dev_user:
                logger.info("開発用ユーザーを作成します")
                hashed_password = get_password_hash("devpass")
                dev_user = models.User(
                    name="開発ユーザー",
                    email="dev@example.com",
                    password_hash=hashed_password,
                    role="admin"
                )
                db.add(dev_user)
                db.commit()
        except Exception as e:
            logger.error(f"初期データ投入エラー: {e}")
        finally:
            db.close()

# シャットダウン時の処理
@router.on_event("shutdown")
async def shutdown_event():
    logger.info("アプリケーション終了")

# データベースからの削除機能
@router.delete("/api/po/delete")
async def delete_purchase_orders(
    data: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    選択されたPOを削除する
    """
    try:
        # POのIDリストを取得
        ids = data.get("ids", [])
        
        if not ids:
            logger.warning("削除対象のPOが指定されていません")
            raise HTTPException(
                status_code=400,
                detail="削除するPOが指定されていません"
            )
        
        # 各POを削除
        deleted_count = 0
        for po_id in ids:
            po = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.po_id == po_id).first()
            if po:
                db.delete(po)
                deleted_count += 1
                logger.info(f"PO削除: ID={po_id}")
                
                # 削除操作のログ記録
                log_entry = models.Log(
                    user_id=current_user.user_id,
                    action="PO削除",
                    processed_data=json.dumps({"po_id": po_id})
                )
                db.add(log_entry)
        
        # 変更をコミット
        db.commit()
        
        logger.info(f"合計{deleted_count}件のPOを削除しました")
        return {
            "success": True,
            "detail": f"{deleted_count}件のPOを削除しました"
        }
    
    except Exception as e:
        db.rollback()  # エラーが発生した場合はロールバック
        logger.error(f"PO削除エラー: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"POの削除中にエラーが発生しました: {str(e)}"
        )

__all__ = ["router"]