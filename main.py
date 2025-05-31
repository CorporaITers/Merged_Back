# main.py - 現行コードをベースにOCR機能を統合した改良版

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
import os
import json
import subprocess
from typing import Optional, Dict, Any, cast
import logging
from dateutil import parser
import mysql.connector
from decimal import Decimal
import pymysql
from collections import defaultdict
from openai import AzureOpenAI
import httpx
from pathlib import Path
import sys
from urllib.parse import unquote
from dotenv import load_dotenv
import traceback
from fastapi.responses import JSONResponse
import camelot.io as camelot
import warnings
from app.app_router import router as po_router
from fastapi.exceptions import RequestValidationError
import tempfile
import csv

# ========== OCR機能の統合（追加） ==========
from app.routes import app as ocr_routes_app  # OCR関連のルート
from app.config import (
    DEV_MODE, LOG_LEVEL, OCR_TEMP_FOLDER, MAX_FILE_SIZE, ALLOWED_EXTENSIONS
)

# ローカル用 .env 読み込み（Azure環境では無視される）
load_dotenv(override=True)

# ログ設定（現行のものを維持）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

# pdfminerのログレベルをERRORに設定（現行のまま）
for logger_name in ["pdfminer", "pdfminer.layout", "pdfminer.converter", "pdfminer.pdfinterp"]:
    logging.getLogger(logger_name).setLevel(logging.ERROR)

# 警告を抑制（現行のまま）
warnings.filterwarnings("ignore", message="Cannot set gray non-stroke color")

# Azure OpenAI クライアント（現行のまま）
client = AzureOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    api_version=os.getenv("OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("OPENAI_API_BASE") or ""
)

# FastAPIアプリケーション作成
app = FastAPI(
    title="PO Management System",
    description="Purchase Order Management with OCR capabilities and Shipping Schedule Integration",
    version="1.0.0",
    debug=DEV_MODE  # config.pyのDEV_MODEを使用
)

# ========== ルーターの統合（重要な修正） ==========
# 既存のPOルーター
app.include_router(po_router)

# OCR機能ルーターの統合（新規追加）
app.mount("/api", ocr_routes_app)  # OCRのエンドポイントを統合

# バリデーションエラーハンドラー（現行のまま）
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"バリデーションエラー: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "message": "入力内容に誤りがあります。"
        }
    )

# CORS設定（現行のまま）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 起動時処理の改良 ==========
@app.on_event("startup")
def on_startup():
    """アプリケーション起動時の初期化処理"""
    logger.info("🚀 PO Management System starting up...")
    
    # データベーステーブル作成（現行のまま）
    from app import models
    from app.database import engine
    models.Base.metadata.create_all(bind=engine)
    
    # OCR用一時ディレクトリの作成（新規追加）
    try:
        os.makedirs(OCR_TEMP_FOLDER, exist_ok=True)
        logger.info(f"📁 OCR一時ディレクトリ作成完了: {OCR_TEMP_FOLDER}")
    except Exception as e:
        logger.error(f"❌ OCR一時ディレクトリ作成失敗: {e}")
    
    # Tesseractの動作確認（新規追加）
    try:
        import pytesseract
        from app.config import TESSERACT_CMD
        
        if TESSERACT_CMD and os.path.exists(TESSERACT_CMD):
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
            logger.info(f"🔍 Tesseract設定完了: {TESSERACT_CMD}")
        else:
            logger.info("🔍 Tesseractはデフォルトパスを使用します")
            
    except Exception as e:
        logger.warning(f"⚠️ Tesseract設定警告: {e}")
    
    # データベース接続テスト（新規追加）
    try:
        from app.database import test_db_connection
        test_db_connection()
        logger.info("✅ データベース接続テスト成功")
    except Exception as e:
        logger.error(f"❌ データベース接続テスト失敗: {e}")
    
    # 古い一時ファイルのクリーンアップ（新規追加）
    cleanup_temp_files()

# MySQL接続情報（現行のまま）
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME")
}

def get_db_connection():
    """データベース接続を取得（現行のまま）"""
    return mysql.connector.connect(**DB_CONFIG)

def format_date(date_obj: Optional[datetime]) -> str:
    """日付オブジェクトを 'YYYY-MM-DD' 形式の文字列に変換（現行のまま）"""
    return date_obj.strftime("%Y-%m-%d") if date_obj else "N/A"

def get_freight_rate(departure_port: str, destination_port: str, shipping_company: str) -> Optional[float]:
    """運賃レートを取得して float 型で返す（現行のまま）"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT freight_rate_usd
            FROM faredate
            WHERE departure_port = %s AND destination_port = %s AND shipping_company = %s
            LIMIT 1;
        """
        cursor.execute(query, (departure_port, destination_port, shipping_company))
        row = cast(Optional[Dict[str, Any]], cursor.fetchone())
        cursor.close()
        conn.close()

        if row and "freight_rate_usd" in row:
            value = row["freight_rate_usd"]

            if isinstance(value, Decimal):
                return float(value)
            else:
                logger.warning(f"Unexpected data type for freight_rate_usd: {type(value)}")

    except Exception as e:
        logger.error(f"[ERROR] 運賃取得失敗: {e}")

    return None

# ========== 一時ファイル管理機能（改良・統合） ==========
def get_temp_file_path(prefix: str, suffix: str) -> str:
    """Azure App Service対応の一時ファイルパス生成"""
    temp_dir = OCR_TEMP_FOLDER  # config.pyの設定を使用
    return os.path.join(temp_dir, f"{prefix}_{os.getpid()}_{int(datetime.now().timestamp())}{suffix}")

def cleanup_temp_files(pattern: str = "*.pdf"):
    """一時ディレクトリの古いファイルをクリーンアップ"""
    import glob
    pattern_path = os.path.join(OCR_TEMP_FOLDER, pattern)
    
    for file_path in glob.glob(pattern_path):
        try:
            # 1時間以上古いファイルを削除
            if os.path.getctime(file_path) < (datetime.now().timestamp() - 3600):
                os.remove(file_path)
                logger.info(f"🧹 古い一時ファイルを削除: {file_path}")
        except Exception as e:
            logger.warning(f"一時ファイル削除失敗: {e}")

# ========== 既存のAPIエンドポイント（現行のまま維持） ==========

# 商品マスタ取得API
TABLE_NAME = "shipping_company"

# テスト用エンドポイント（現行のまま）
@app.get("/test-env")
def test_env():
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        return {"status": "success", "openai_key_snippet": openai_key[:5] + "..." + openai_key[-5:]}
    else:
        return {"status": "failure", "error": "OPENAI_API_KEY not found"}

@app.get("/")
async def root():
    return {"message": "PO Management System with OCR - Hello, FastAPI!"}

# リクエストボディ定義（現行のまま）
class ShippingRequest(BaseModel):
    departure_port: str
    destination_port: str
    etd_date: Optional[str] = None
    eta_date: Optional[str] = None

class ScheduleRequest(BaseModel):
    departure_port: str
    destination_port: str
    etd_date: Optional[str]
    eta_date: Optional[str]

class FeedbackRequest(BaseModel):
    url: str
    etd: str
    eta: str
    feedback: str

# ========== PDFスケジュール解析機能（現行のまま） ==========
async def extract_schedule_positions(
    url: str,
    departure: str,
    destination: str,
    etd_date: Optional[datetime] = None,
    eta_date: Optional[datetime] = None
):
    """PDFスケジュール解析（現行のまま - 一時ファイル処理は既に改善済み）"""
    
    import os
    import json
    import re
    import requests
    from datetime import datetime

    DESTINATION_ALIASES = {
        "New York": ["NEW YORK", "NYC", "NEWYORK", "N.Y.", "NY", "NYO"],
        "Los Angeles": ["LOS ANGELES", "LA", "L.A."],
        "Rotterdam": ["ROTTERDAM"],
        "Hamburg": ["HAMBURG"],
        "Norfolk": ["NORFOLK", "ORF"],
        "Savannah": ["SAVANNAH", "SAV"],
        "Charleston": ["CHARLESTON"],
        "Miami": ["MIAMI", "MIA"],
        "Oakland": ["OAKLAND", "OAK"],
        "Houston": ["HOUSTON", "HOU"],
        "Dallas": ["DALLAS", "FWO", "FORT WORTH", "FT WORTH"],
        "Memphis": ["MEMPHIS", "MEM"],
        "Atlanta": ["ATLANTA", "ATL"],
        "Chicago": ["CHICAGO", "CHI"],
        "Columbus": ["COLUMBUS", "CMH"],
        "Singapore": ["SINGAPORE", "SGP"],
        "Jakarta": ["JAKARTA"],
        "Port Klang": ["PORT KLANG", "PORT KLANG (W)", "PORT KLANG (N)", "PKG", "PKW"],
        "Penang": ["PENANG"],
        "Surabaya": ["SURABAYA"],
        "Bangkok": ["BANGKOK"],
        "Ho Chi Minh": ["HO CHI MINH", "HCM", "SAIGON"],
        "Haiphong": ["HAIPHONG", "HPH"],
        "Hanoi": ["HANOI"],
        "Manila": ["MANILA", "MNL"],
        "Busan": ["BUSAN", "PUSAN", "PUS"],
        "Hong Kong": ["HONG KONG", "HK", "HKG"],
        "Kaohsiung": ["KAOHSIUNG", "KHH"],
        "Sydney": ["SYDNEY", "SYD"],
        "Melbourne": ["MELBOURNE", "MEL"],
        "Adelaide": ["ADELAIDE", "ADL"],
        "Fremantle": ["FREMANTLE", "FRE"],
        "Brisbane": ["BRISBANE", "BNE"],
        "Xiamen": ["XIAMEN"],
        "Qingdao": ["QINGDAO", "TSINGTAO"],
        "Dalian": ["DALIAN"],
        "Shanghai": ["SHANGHAI", "SHA"],
        "Ningbo": ["NINGBO"],
        "Shekou": ["SHEKOU"],
        "Yantian": ["YANTIAN", "YTN"],
        "Nansha": ["NANSHA"],
        "Shenzhen": ["SHENZHEN"],
        "Tanjung Pelepas": ["TANJUNG PELEPAS", "TPP"],
        "Port Kelang": ["PORT KELANG", "PORTKLANG"],
    }

    if not etd_date and not eta_date:
        return {"error": "ETDかETAのいずれかを指定してください。"}

    base_date = etd_date or eta_date

    # PDFをダウンロード
    logger.info(f"📥 PDFリンクにアクセス中: {url}")
    response = requests.get(url)
    
    if response.status_code != 200:
        logger.error(f"❌ PDFのダウンロードに失敗しました。ステータスコード: {response.status_code}")
        return None

    # 一時ファイルを使用した安全な処理（現行コードの改良版）
    temp_pdf_file = None
    try:
        # OCR_TEMP_FOLDERを使用して一時ファイル作成
        temp_pdf_file = tempfile.NamedTemporaryFile(
            suffix=".pdf", 
            delete=False,
            dir=OCR_TEMP_FOLDER  # config.pyの設定を使用
        )
        
        logger.info(f"📁 一時PDFファイルを作成: {temp_pdf_file.name}")
        temp_pdf_file.write(response.content)
        temp_pdf_file.flush()
        temp_pdf_file.close()

        # エイリアス生成（大文字化して正規化）
        aliases = DESTINATION_ALIASES.get(destination, [destination])
        aliases = [a.upper() for a in aliases]

        # PDFテーブル抽出
        logger.info(f"🔍 PDFテーブル抽出開始: {temp_pdf_file.name}")
        tables = camelot.read_pdf(temp_pdf_file.name, pages="all", flavor="stream")
        logger.info(f"抽出されたテーブル数: {len(tables)}")

        # テーブルデータを文字列形式に変換
        table_data = ""
        for i, table in enumerate(tables):
            table_data += f"\n--- テーブル {i + 1} ---\n"
            table_data += table.df.to_string()

        prompt = f"""
以下はPDFから抽出されたスケジュール候補の行です。
出発地「{departure}」と目的地「{destination}」（別名: {', '.join(aliases)}）に関連する、
最も{format_date(base_date)}に近いスケジュール（船名・航海番号・ETD・ETA）を1件だけ抽出してください。

その抽出したスケジュールが複数の船名を有するかどうかを確認し、もし有する場合は1st Vesselの船名を選択してください。
（有しない場合はそのままの船名を選択してください）

なお、出港日{etd_date}は出発地「{departure}」の日付を基準に、到着日{eta_date}は目的地「{destination}」の日付を基準として、結果を出力してください。

出力形式（必ずJSON形式）:
{{
  "vessel": "船名",
  "voy": "航海番号",
  "etd": "MM/DD または MM/DD - MM/DD",
  "eta": "MM/DD"
}}

なぜそのスケジュールを選択したのか、理由も簡潔に出力してください。
---
{table_data}
"""

        chat_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "あなたは貿易実務に詳しい熟練の船便選定アドバイザーです。"},
                {"role": "user", "content": prompt},
            ]
        )

        reply_text = chat_response.choices[0].message.content

        if reply_text is None:
            logger.warning("[WARNING] ChatGPTの返答が空またはNoneです")
            return {
                "error": "ChatGPTの返答が空またはNoneです", 
                "raw_response": "",
                "vessel": "",
                "voy": "",
                "etd": "",
                "eta": "",
                "fare": "",
                "schedule_url": url
            }
            
        match = re.search(r'\{[\s\S]*?\}', reply_text)
        if not match:
            logger.warning("[WARNING] ChatGPTの返答がJSON形式でないため解析不可")
            return {
                "error": "ChatGPTの返答がJSON形式で含まれていません", 
                "raw_response": reply_text,
                "vessel": "",
                "voy": "",
                "etd": "",
                "eta": "",
                "fare": "",
                "schedule_url": url
            }

        try:
            info = json.loads(match.group())
            etd_date_str = info.get("etd")
            eta_date_str = info.get("eta")
            vessel = info.get("vessel")
            voyage = info.get("voy")
            company = info.get("company")

            # デフォルト値の設定（companyが取得できない場合）
            if not company:
                company = "Unknown"

            # ログファイルも一時ディレクトリに作成
            log_path = os.path.join(OCR_TEMP_FOLDER, "gpt_feedback_log.csv")
            new_entry = [
                datetime.now().isoformat(),
                url,
                departure,
                destination,
                format_date(base_date),
                etd_date_str,
                eta_date_str,
                vessel,
                voyage,
                company,
                "pending"
            ]

            file_exists = os.path.exists(log_path)
            with open(log_path, "a", newline='', encoding='utf-8') as log_file:
                writer = csv.writer(log_file)
                if not file_exists:
                    writer.writerow(["timestamp", "url", "departure", "destination", "input_date", "etd", "eta", "vessel", "voy", "company", "feedback"])
                writer.writerow(new_entry)

            return {
                "company": company,
                "fare": "$",
                "etd": etd_date_str,
                "eta": eta_date_str,
                "vessel": vessel,
                "voy": voyage,
                "schedule_url": url,
                "raw_response": reply_text
            }
        except Exception as e:
            return {"error": "ChatGPTの返答がパースできませんでした", "raw_response": reply_text}

    except Exception as e:
        logger.error(f"PDF解析失敗: {e}")
        return None

    finally:
        # 確実なファイルクリーンアップ
        if temp_pdf_file:
            try:
                if os.path.exists(temp_pdf_file.name):
                    os.unlink(temp_pdf_file.name)
                    logger.info(f"🧹 一時PDFファイルを削除しました: {temp_pdf_file.name}")
            except Exception as cleanup_error:
                logger.warning(f"[WARN] PDF削除に失敗: {cleanup_error}")

# ========== 既存のPDFリンク取得機能（現行のまま） ==========

async def get_pdf_links_from_one(destination_keyword: str) -> list[str]:
    """ONE社のPDFリンク取得（現行のまま）"""
    result = None
    try:
        script_path = Path(__file__).resolve().parent / "app" / "get_pdf_links.py"
        cwd_path = script_path.parent

        result = subprocess.run(
            [sys.executable, str(script_path), destination_keyword, "--silent"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(cwd_path),
            env=os.environ.copy(),
        )

        if result.stdout:
            logger.info(f"[DEBUG] get_pdf_links.py stdout:\n{result.stdout}")
        
        return json.loads(result.stdout)
    
    except json.JSONDecodeError as je:
        logger.error(f"[ERROR] JSON Decode Error: {je}")
        if result and result.stdout:
            logger.error(f"[DEBUG] 実際の出力内容: {result.stdout}")
        else:
            logger.error("[DEBUG] stdout is None")
        return []
    
    except subprocess.CalledProcessError as cpe:
        logger.error(f"[CalledProcessError] stderr:\n{cpe.stderr}")
        if cpe.stdout:
            logger.error(f"[CalledProcessError] stdout:\n{cpe.stdout}")
        else:
            logger.error("[CalledProcessError] stdout is None")
        return []
    
    except Exception as e:
        logger.error(f"[ERROR] ONE get_pdf_links 実行失敗: {e}")
        return []

async def get_pdf_links_from_cosco(destination_keyword: str) -> list[str]:
    """COSCO社のPDFリンク取得（現行のまま）"""
    result = None
    try:
        script_path = Path(__file__).resolve().parent / "app" / "get_cosco_pdf_links.py"
        cwd_path = script_path.parent

        result = subprocess.run(
            [sys.executable, str(script_path), destination_keyword, "--silent"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(cwd_path),
            env=os.environ.copy(),
        )

        if result.stdout:
            logger.info(f"[COSCO PDFリンク取得] stdout:\n{result.stdout}")

        return json.loads(result.stdout)

    except json.JSONDecodeError as je:
        logger.error(f"[ERROR] JSON Decode Error: {je}")
        if result and result.stdout:
            logger.error(f"[DEBUG] 実際の出力内容: {result.stdout}")
        else:
            logger.error("[DEBUG] stdout is None")
        return []

    except subprocess.CalledProcessError as spe:
        logger.error(f"[ERROR] CalledProcessError: {spe}")
        if spe.stdout:
            logger.error(f"[stderr]\n{spe.stderr}")
        else:
            logger.error("[stderr] None")

        if spe.stdout:
            logger.error(f"[stdout]\n{spe.stdout}")
        else:
            logger.error("[stdout] None")
        return []

    except Exception as e:
        logger.error(f"[ERROR] COSCO get_pdf_links 実行失敗: {e}")
        return []

async def get_pdf_links_from_kinka(destination_keyword: str) -> list[str]:
    """KINKA社のPDFリンク取得（現行のまま）"""
    result = None
    try:
        script_path = Path(__file__).resolve().parent / "app" / "get_kinka_pdf_links.py"
        cwd_path = script_path.parent

        result = subprocess.run(
            [sys.executable, str(script_path), destination_keyword, "--silent"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(cwd_path),
            env=os.environ.copy(),
        )

        if result.stdout:
            logger.info(f"[KINKA PDFリンク取得] stdout:\n{result.stdout}")
        
        return json.loads(result.stdout)

    except json.JSONDecodeError as je:
        logger.error(f"[ERROR] JSON Decode Error: {je}")
        if result and result.stdout:
            logger.error(f"[DEBUG] 実際の出力内容: {result.stdout}")
        else:
            logger.error("[DEBUG] stdout is None")
        return []
    
    except Exception as e:
        logger.error(f"[ERROR] KINKA get_pdf_links 実行失敗: {e}")
        return []

async def get_pdf_links_from_shipmentlink(departure_port: str, destination_port: str) -> list[str]:
    """Shipmentlink のPDFリンク取得（現行のまま）"""
    result = None
    try:
        script_path = Path(__file__).resolve().parent / "app" / "get_shipmentlink_pdf_links.py"
        cwd_path = script_path.parent

        result = subprocess.run(
            [sys.executable, str(script_path), departure_port, destination_port, "--silent"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(cwd_path),
            env=os.environ.copy(),
        )

        logger.info(f"[Shipmentlink PDF取得] raw stdout:\n{result.stdout}")
        raw_links = json.loads(result.stdout)
        decoded_links = [unquote(url) for url in raw_links]
        logger.info(f"[Shipmentlink PDF取得] decoded:\n{decoded_links}")
        
        return decoded_links
    except Exception as e:
        logger.error(f"[Shipmentlink取得失敗] {e}")
        return []

# ========== 船舶スケジュール推奨API（現行のまま） ==========
@app.post("/recommend-shipping")
async def recommend_shipping(req: ShippingRequest):
    """船舶スケジュール推奨API（現行のまま）"""
    logger.info("📦 リクエスト受信:")
    logger.info(f"  Departure Port: {req.departure_port}")
    logger.info(f"  Destination Port: {req.destination_port}")
    logger.info(f"  ETD: {req.etd_date}")
    logger.info(f"  ETA: {req.eta_date}")

    if not req.etd_date and not req.eta_date:
        return {"error": "ETDかETAのいずれかを指定してください。"}

    destination = req.destination_port
    departure = req.departure_port
    keyword = destination
    etd_date = datetime.strptime(req.etd_date, "%Y-%m-%d") if req.etd_date else None
    eta_date = datetime.strptime(req.eta_date, "%Y-%m-%d") if req.eta_date else None

    results = []

    # ONE社の処理
    logger.info(f"🔍 ONE社 get_pdf_links.py に渡すキーワード: '{keyword}'")
    pdf_urls_one = await get_pdf_links_from_one(keyword)
    if not pdf_urls_one:
        logger.warning("⚠️ ONE社のPDFリンク取得に失敗しました。")
    else:
        for pdf_url in pdf_urls_one:
            result = await extract_schedule_positions(
                url=pdf_url,
                departure=departure,
                destination=destination,
                etd_date=etd_date,
                eta_date=eta_date
            )
            if result:
                result["company"] = "ONE"
                result["fare"] = str(get_freight_rate(departure, destination, "ONE")) if not None else "N/A"
                results.append(result)
                logger.info(f"[ONE社マッチ] {result}")
                break

    # COSCO社の処理
    logger.info(f"🔍 COSCO社 get_cosco_pdf_links.py に渡すキーワード: '{keyword}'")
    pdf_urls_cosco = await get_pdf_links_from_cosco(keyword)
    if not pdf_urls_cosco:
        logger.warning("⚠️ COSCO社のPDFリンク取得に失敗しました。")
    else:
        for pdf_url in pdf_urls_cosco:
            result = await extract_schedule_positions(
                url=pdf_url,
                departure=departure,
                destination=destination,
                etd_date=etd_date,
                eta_date=eta_date
            )
            if result:
                result["company"] = "COSCO"
                result["fare"] = str(get_freight_rate(departure, destination, "COSCO")) if not None else "N/A"
                results.append(result)
                logger.info(f"[COSCO社マッチ] {result}")
                break

    # KINKA社の処理（上海の場合のみ）
    if "上海" in keyword or "Shanghai" in keyword:
        logger.info(f"🔍 KINKA社 get_kinka_pdf_links.py に渡すキーワード: '{keyword}'")
        pdf_urls_kinka = await get_pdf_links_from_kinka(keyword)
        if not pdf_urls_kinka:
            logger.warning("⚠️ KINKA社のPDFリンク取得に失敗しました。")
        else:
            for pdf_url in pdf_urls_kinka:
                result = await extract_schedule_positions(
                    url=pdf_url,
                    departure=departure,
                    destination=destination,
                    etd_date=etd_date,
                    eta_date=eta_date
                )
                if result:
                    result["company"] = "KINKA"
                    result["fare"] = str(get_freight_rate(departure, destination, "KINKA")) if not None else "N/A"
                    results.append(result)
                    logger.info(f"[KINKA社マッチ] {result}")
                    break
    else:
        logger.info("📛 KINKA社は『上海』のときのみ検索対象となるため、今回はスキップされました。")

    # Evergreen社の処理
    logger.info(f"🔍 Evergreen社 get_pdf_links.py に渡すキーワード: '{keyword}'")
    pdf_urls_shipmentlink = await get_pdf_links_from_shipmentlink(departure, destination)
    
    if not pdf_urls_shipmentlink:
        logger.warning("⚠️ Evergreen社のPDFリンク取得に失敗しました。")
    else:
        success = False
        for pdf_url in pdf_urls_shipmentlink:
            result = await extract_schedule_positions(
                url=pdf_url,
                departure=departure,
                destination=destination,
                etd_date=etd_date,
                eta_date=eta_date
            )
            if result:
                result["company"] = "EVERGREEN"
                result["fare"] = str(get_freight_rate(departure, destination, "Shipmentlink")) if not None else "N/A"
                results.append(result)
                logger.info(f"[Evergreen社マッチ] {result}")
                success = True
                break
        if not success:
            logger.warning("⚠️ Evergreen社のスケジュール抽出に失敗しました。")

    # 結果返却
    if results:
        logger.info(f"[✅MATCHED] {len(results)}件のスケジュールが見つかりました")
        return results
    else:
        logger.warning("❌ 全社のいずれにもマッチしませんでした")
        return []

@app.post("/update-feedback")
async def update_feedback(data: FeedbackRequest):
    """フィードバック更新API（現行のまま、ただし一時ディレクトリ使用）"""
    logger.info(f"フィードバック受信: URL={data.url}, ETD={data.etd}, ETA={data.eta}, Feedback={data.feedback}")
    try:
        # ログファイルも一時ディレクトリに保存
        log_path = os.path.join(OCR_TEMP_FOLDER, "gpt_feedback_log.csv")
        
        file_exists = os.path.exists(log_path)
        with open(log_path, "a", encoding="utf-8", newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "url", "etd", "eta", "feedback"])
            writer.writerow([
                datetime.now().isoformat(),
                data.url,
                data.etd,
                data.eta,
                data.feedback
            ])
        
        return {"message": "フィードバックを記録しました。"}
    except Exception as e:
        logger.exception("フィードバック記録中にエラー")
        raise HTTPException(status_code=500, detail="フィードバックの保存に失敗しました。")

# ========== ヘルスチェック（OCR機能対応版） ==========
@app.get("/health")
async def health_check():
    """
    Azure App Service のヘルスチェック用
    （データベース、OpenAI、OCR機能、一時ディレクトリアクセス確認付き）
    """
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "services": {}
        }
        
        # データベース接続確認
        try:
            conn = get_db_connection()
            conn.close()
            health_status["services"]["database"] = "connected"
        except Exception as db_error:
            health_status["services"]["database"] = f"error: {str(db_error)}"
        
        # OpenAI接続確認
        try:
            test_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1
            )
            health_status["services"]["openai"] = "connected"
        except Exception as openai_error:
            health_status["services"]["openai"] = f"error: {str(openai_error)}"
        
        # 一時ディレクトリの書き込み権限確認
        try:
            temp_test_file = tempfile.NamedTemporaryFile(delete=True, dir=OCR_TEMP_FOLDER)
            temp_test_file.write(b"health check")
            temp_test_file.close()
            health_status["services"]["temp_directory"] = "writable"
        except Exception as temp_error:
            health_status["services"]["temp_directory"] = f"error: {str(temp_error)}"
        
        # Tesseract確認
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            health_status["services"]["tesseract"] = "available"
        except Exception as tesseract_error:
            health_status["services"]["tesseract"] = f"error: {str(tesseract_error)}"
        
        # 設定情報
        health_status["config"] = {
            "ocr_temp_folder": OCR_TEMP_FOLDER,
            "max_file_size_mb": MAX_FILE_SIZE / (1024 * 1024),
            "allowed_extensions": list(ALLOWED_EXTENSIONS),
            "dev_mode": DEV_MODE
        }
        
        # 全体的なステータス判定
        error_services = [k for k, v in health_status["services"].items() if "error" in str(v)]
        if error_services:
            health_status["status"] = "degraded"
            health_status["warning"] = f"以下のサービスにエラーがあります: {', '.join(error_services)}"
        
        return health_status
        
    except Exception as e:
        return {
            "status": "unhealthy", 
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# ========== 終了時処理の追加 ==========
@app.on_event("shutdown")
async def shutdown_event():
    """アプリケーション終了時の処理"""
    logger.info("🛑 PO Management System shutting down...")
    
    # 終了時に一時ファイルをクリーンアップ
    try:
        cleanup_temp_files("*")  # 全ての一時ファイルを削除
        logger.info("🧹 終了時クリーンアップ完了")
    except Exception as e:
        logger.warning(f"終了時クリーンアップエラー: {e}")

# エラーハンドリングミドルウェア（現行のまま）
@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.exception("未処理の例外が発生しました:\n%s", error_trace)
        
        return JSONResponse(
            status_code=500,
            content={"detail": error_trace}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        reload=DEV_MODE,  # 開発モードの場合のみreload
        log_level=LOG_LEVEL.lower()
    )