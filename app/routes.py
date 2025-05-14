# routes.py - PO関連のエンドポイント（FastAPI実装）

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import os
from sqlalchemy.orm import Session
import shutil

# 既存のインポート文はそのまま保持する

app = FastAPI()

# CORSミドルウェアの設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# アップロードフォルダの設定
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'backend/uploads')
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

# アップロードフォルダが存在しない場合は作成
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.post("/api/ocr/upload")
async def upload_file(
    file: UploadFile = File(...)
):
    """
    ファイルをアップロードしてOCR処理を開始します。
    """
    if not file:
        raise HTTPException(status_code=400, detail="ファイルがありません")
    
    if file.filename == "":
        raise HTTPException(status_code=400, detail="選択されたファイルがありません")
    
    if not allowed_file(file.filename):
        raise HTTPException(status_code=422, detail="許可されていないファイル形式です")
    
    # セキュアなファイル名の生成
    filename = file.filename
    safe_filename = filename.replace(" ", "_")
    
    # ファイルのパスを設定
    filepath = os.path.join(UPLOAD_FOLDER, safe_filename)
    
    # ファイルを保存
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # OCR IDを生成（実際の実装ではOCR処理のIDを返します）
    ocr_id = "dummy-ocr-id"
    
    return {
        "status": "success",
        "filename": safe_filename,
        "message": "ファイルが正常にアップロードされました",
        "ocrId": ocr_id
    }

@app.get("/api/ocr/status/{ocr_id}")
async def check_ocr_status(ocr_id: str):
    """
    OCR処理のステータスを確認します。
    """
    # 実際の実装ではデータベースなどからステータスを取得します
    # このダミー実装では常に completed を返します
    return {
        "status": "completed",
        "ocr_id": ocr_id
    }

@app.get("/api/ocr/extract/{ocr_id}")
async def get_ocr_data(ocr_id: str):
    """
    OCR処理の結果を取得します。
    """
    # 実際の実装ではOCR結果をデータベースから取得します
    # このダミー実装ではサンプルデータを返します
    sample_data = {
        "customer_name": "サンプル顧客",
        "po_number": "PO-2024-001",
        "currency": "JPY",
        "products": [
            {
                "product_name": "サンプル製品",
                "quantity": "100",
                "unit_price": "1000",
                "amount": "100000"
            }
        ],
        "total_amount": "100000",
        "payment_terms": "30日以内",
        "shipping_terms": "CIF",
        "destination": "東京"
    }
    
    return {
        "status": "success",
        "data": sample_data
    }

@app.post("/api/po/register")
async def register_po(
    po_data: dict,
    current_user: dict = Depends(lambda: {"id": 1, "name": "開発ユーザー"}),  # ダミーの依存関係
):
    """
    POデータを登録します。
    成功時には登録完了メッセージと共にステータスを返します。
    """
    try:
        # POデータの検証
        required_fields = ["customer_name", "po_number", "products"]
        for field in required_fields:
            if field not in po_data:
                raise HTTPException(status_code=400, detail=f"必須フィールド '{field}' がありません")
        
        # 製品情報の検証
        if not isinstance(po_data["products"], list) or len(po_data["products"]) == 0:
            raise HTTPException(status_code=400, detail="製品情報が正しくありません")
        
        for product in po_data["products"]:
            if not all(k in product for k in ["product_name", "quantity", "unit_price", "amount"]):
                raise HTTPException(status_code=400, detail="製品情報に必須フィールドがありません")
        
        # 実際の登録処理（ここではダミー）
        # 実際の実装ではデータベースに登録します
        
        # 成功応答を返す（登録成功時には明示的に成功ステータスを返す）
        return {
            "success": True,
            "poId": "dummy-po-id",
            "message": "PO情報が正常に登録されました"
        }
    
    except HTTPException as e:
        # FastAPIのHTTPExceptionはそのまま再スロー
        raise e
    except Exception as e:
        # その他の例外はエラーメッセージとして返す
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"登録に失敗しました: {str(e)}"}
        )