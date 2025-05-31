# routes.py - 現行config.pyを使用した修正版

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import os
import uuid
import json
from datetime import datetime
from sqlalchemy.orm import Session

# OCRサービスの関数をインポート
from app.ocr_service import process_ocr_with_enhanced_extraction

# データベース関連のインポート（既存）
from app.database import get_db
from app import models

# 現行config.pyから設定をインポート
from app.config import MAX_FILE_SIZE, ALLOWED_EXTENSIONS

app = FastAPI()

# CORSミドルウェアの設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番環境では特定のドメインのみ許可
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def allowed_file(filename):
    """ファイル形式チェック（現行config.pyのALLOWED_EXTENSIONSを使用）"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.post("/api/ocr/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    ファイルをアップロードしてOCR処理を開始します。
    現行システムとの互換性を保った修正版
    """
    if not file:
        raise HTTPException(status_code=400, detail="ファイルがありません")
    
    if file.filename == "":
        raise HTTPException(status_code=400, detail="選択されたファイルがありません")
    
    if not allowed_file(file.filename):
        raise HTTPException(status_code=422, detail="許可されていないファイル形式です")
    
    # ファイルデータを読み取り
    try:
        file_data = await file.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ファイル読み取りエラー: {str(e)}")
    
    # ファイルサイズチェック（現行config.pyのMAX_FILE_SIZEを使用）
    if len(file_data) > MAX_FILE_SIZE:
        max_size_mb = MAX_FILE_SIZE / (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"ファイルサイズが大きすぎます（最大{max_size_mb:.0f}MB）")
    
    # データベースにOCR記録を作成
    try:
        ocr_result = models.OCRResult(
            status="processing",
            raw_text="",  # Text型なので空文字列
            processed_data="{}",
            ocrresultscol1="uploaded_file"  # デフォルト値以外を設定
        )
        db.add(ocr_result)
        db.commit()
        db.refresh(ocr_result)
        
        # 生成されたocr_idを取得
        ocr_id = ocr_result.ocr_id
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"データベースエラー: {str(e)}")
    
    # バックグラウンドでOCR処理を実行
    background_tasks.add_task(
        process_ocr_with_enhanced_extraction,
        file_data,
        file.filename or "",
        ocr_id  # 数値型のIDを渡す # type: ignore
    )
    
    return {
        "status": "success",
        "filename": file.filename,
        "message": "ファイルが正常にアップロードされ、OCR処理を開始しました",
        "ocrId": str(ocr_id)  # 文字列として返す
    }

@app.get("/api/ocr/status/{ocr_id}")
async def check_ocr_status(ocr_id: str, db: Session = Depends(get_db)):
    """
    OCR処理のステータスを確認します。
    """
    try:
        # 文字列のocr_idを数値に変換
        numeric_ocr_id = int(ocr_id)
        
        # OCR結果を検索
        ocr_result = db.query(models.OCRResult).filter(
            models.OCRResult.ocr_id == numeric_ocr_id
        ).first()
        
        if not ocr_result:
            raise HTTPException(status_code=404, detail="OCR結果が見つかりません")
        
        return {
            "status": ocr_result.status,
            "ocr_id": ocr_id
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="無効なOCR IDです")
    except Exception as e:
        return {
            "status": "error",
            "ocr_id": ocr_id,
            "message": str(e)
        }

@app.get("/api/ocr/extract/{ocr_id}")
async def get_ocr_data(ocr_id: str, db: Session = Depends(get_db)):
    """
    OCR処理の結果を取得します。
    """
    try:
        # 文字列のocr_idを数値に変換
        numeric_ocr_id = int(ocr_id)
        
        # OCR結果を検索
        ocr_result = db.query(models.OCRResult).filter(
            models.OCRResult.ocr_id == numeric_ocr_id
        ).first()
        
        if not ocr_result:
            raise HTTPException(status_code=404, detail="OCR結果が見つかりません")
        
        if ocr_result.status != "completed":  # type: ignore
            raise HTTPException(status_code=202, detail="OCR処理がまだ完了していません")
        
        # processed_dataからデータを取得
        processed_data_str = ocr_result.processed_data or "{}"
        
        try:
            processed_data = json.loads(str(processed_data_str))
        except json.JSONDecodeError:
            processed_data = {}
        
        # 抽出されたデータを取得
        extracted_data = processed_data.get("data", {})
        
        return {
            "status": "success",
            "data": extracted_data
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="無効なOCR IDです")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"データ取得エラー: {str(e)}")

@app.post("/api/po/register")
async def register_po(
    po_data: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(lambda: {"id": 1, "name": "開発ユーザー"})
):
    """
    POデータを登録します。
    現行データベースモデルに対応した完全実装版
    """
    try:
        # POデータの検証
        required_fields = ["customer", "poNumber", "products"]
        for field in required_fields:
            if field not in po_data:
                raise HTTPException(status_code=400, detail=f"必須フィールド '{field}' がありません")
        
        # 製品情報の検証
        if not isinstance(po_data["products"], list) or len(po_data["products"]) == 0:
            raise HTTPException(status_code=400, detail="製品情報が正しくありません")
        
        for product in po_data["products"]:
            required_product_fields = ["name", "quantity", "unitPrice", "amount"]
            if not all(k in product for k in required_product_fields):
                raise HTTPException(status_code=400, detail="製品情報に必須フィールドがありません")
        
        # PurchaseOrderの作成
        purchase_order = models.PurchaseOrder(
            user_id=current_user["id"],
            customer_name=po_data["customer"],
            po_number=po_data["poNumber"],
            currency=po_data.get("currency", "USD"),
            total_amount=float(po_data.get("totalAmount", "0")),
            payment_terms=po_data.get("paymentTerms", ""),
            shipping_terms=po_data.get("terms", ""),
            destination=po_data.get("destination", ""),
            status="手配前"
        )
        
        db.add(purchase_order)
        db.commit()
        db.refresh(purchase_order)
        
        # OrderItemsの作成
        for product in po_data["products"]:
            # 数値変換の安全な処理
            try:
                quantity = int(float(product["quantity"])) if product["quantity"] else 0
            except (ValueError, TypeError):
                quantity = 0
            
            try:
                unit_price = float(product["unitPrice"]) if product["unitPrice"] else 0.0
            except (ValueError, TypeError):
                unit_price = 0.0
            
            try:
                subtotal = float(product["amount"]) if product["amount"] else 0.0
            except (ValueError, TypeError):
                subtotal = 0.0
            
            order_item = models.OrderItem(
                po_id=purchase_order.po_id,
                product_name=product["name"],
                quantity=quantity,
                unit_price=unit_price,
                subtotal=subtotal
            )
            db.add(order_item)
        
        # Inputテーブルの作成
        try:
            po_acquisition_date = datetime.strptime(
                po_data.get("po_acquisition_date", datetime.now().strftime("%Y-%m-%d")), 
                "%Y-%m-%d"
            ).date()
        except ValueError:
            po_acquisition_date = datetime.now().date()
        
        input_record = models.Input(
            po_id=purchase_order.po_id,
            shipment_arrangement=po_data.get("shipment_arrangement", "手配前"),
            po_acquisition_date=po_acquisition_date,
            organization=po_data.get("organization", ""),
            invoice_number=po_data.get("invoice_number", ""),
            payment_status=po_data.get("payment_status", "未払い"),
            booking_number=po_data.get("booking_number"),
            memo=po_data.get("memo", "")
        )
        db.add(input_record)
        
        db.commit()
        
        return {
            "success": True,
            "poId": purchase_order.po_id,
            "message": "PO情報が正常に登録されました"
        }
    
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"登録に失敗しました: {str(e)}"}
        )