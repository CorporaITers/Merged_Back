from fastapi import FastAPI,HTTPException,Request
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
# from openai import OpenAI
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
from app.app_router import router as po_router  # ← 上で変換したモジュールを読み込む
from fastapi.exceptions import RequestValidationError

# ローカル用 .env 読み込み（Azure環境では無視される）
load_dotenv()

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

# pdfminerのログレベルをERRORに設定
for logger_name in ["pdfminer", "pdfminer.layout", "pdfminer.converter", "pdfminer.pdfinterp"]:
    logging.getLogger(logger_name).setLevel(logging.ERROR)

# "Cannot set gray non-stroke color" の警告を抑制
warnings.filterwarnings("ignore", message="Cannot set gray non-stroke color")

# api_key = os.getenv("OPENAI_API_KEY")
# if not api_key:
#     raise RuntimeError("❌ OPENAI_API_KEY が設定されていません。Azure の構成または .env を確認してください。")

# client = OpenAI(api_key=api_key)

client = AzureOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    api_version=os.getenv("OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("OPENAI_API_BASE") or ""
)

app = FastAPI()

app.include_router(po_router)

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

# CORS設定（Next.jsとの連携のため）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    from app import models
    from app.database import engine
    models.Base.metadata.create_all(bind=engine)

# MySQL接続情報
DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "tech0-gen-8-step4-dtx-db.mysql.database.azure.com"),
    "user": os.getenv("MYSQL_USER", "ryoueno"),
    "password": os.getenv("MYSQL_PASSWORD", "tech0-dtxdb"),
    "database": "corporaiters"
}

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

def format_date(date_obj: Optional[datetime]) -> str:
    """ 日付オブジェクトを 'YYYY-MM-DD' 形式の文字列に変換 """
    return date_obj.strftime("%Y-%m-%d") if date_obj else "N/A"

# 🔽 この下に追加
def get_freight_rate(departure_port: str, destination_port: str, shipping_company: str) -> Optional[float]:
    """
    運賃レートを取得して float 型で返す。取得できない場合は None を返す。
    """
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

            # ✅ Decimal を float に変換して返す
            if isinstance(value, Decimal):
                return float(value)
            else:
                logger.warning(f"Unexpected data type for freight_rate_usd: {type(value)}")

    except Exception as e:
        logger.error(f"[ERROR] 運賃取得失敗: {e}")

    return None

# 商品マスタ取得API
TABLE_NAME = "shipping_company"

#テスト用エンドポイント
@app.get("/test-env")
def test_env():
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        return {"status": "success", "openai_key_snippet": openai_key[:5] + "..." + openai_key[-5:]}
    else:
        return {"status": "failure", "error": "OPENAI_API_KEY not found"}

@app.get("/")
async def root():
    return {"message": "Hello, FastAPI!"}

# リクエストボディ定義
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

async def extract_schedule_positions(
    url: str,
    departure: str,
    destination: str,
    etd_date: Optional[datetime] = None,
    eta_date: Optional[datetime] = None
):
    
    import os
    import csv
    import json
    import re
    import requests
    # import fitz  # PyMuPDF
    from datetime import datetime
    # from openai import OpenAI

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
        "Port Kelang": ["PORT KELANG", "PORTKLANG"],  # 通称違い対応
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

    logger.info("📁 temp_schedule.pdf を保存中...")
    with open("temp_schedule.pdf", "wb") as f:
        f.write(response.content)
    logger.info("📄 PDFファイルをtemp_schedule.pdfとして保存しました。")

    doc = None
    try:
        # logger.info("🔍 PDFを開いてテキスト抽出を開始します。")
        # doc = fitz.open("temp_schedule.pdf")
        # full_text = "\n".join(page.get_text("text") for page in doc)
        # logger.info("✅ PDFからのテキスト抽出完了。")

        # エイリアス生成（大文字化して正規化）
        aliases = DESTINATION_ALIASES.get(destination, [destination])
        aliases = [a.upper() for a in aliases]

        # 候補行のみ抽出（日付 + 目的地エイリアスを含む行）
        # lines = full_text.splitlines()
        # candidate_lines = set()
        # for i in range(len(lines)):
        #     line_upper = lines[i].upper()
        #     if re.search(r'\d{1,2}/\d{1,2}', line_upper) and any(alias in line_upper for alias in aliases):
        #         block = lines[max(0, i - 2):min(len(lines), i + 3)]
        #         candidate_lines.update(block)

        # # トークン削減のため、文字数制限（例: 4096文字）
        # condensed_text = "\n".join(candidate_lines)
        # if len(condensed_text) > 4096:
        #     condensed_text = condensed_text[:4096]  # GPT-4oのトークン制限に対応

        # Camelotでテーブル抽出
        tables = camelot.read_pdf("temp_schedule.pdf", pages="all", flavor="stream")
        logger.info(f"抽出されたテーブル数: {len(tables)}")
        # closest_entry = None
        # closest_diff = float("inf")

        # テーブルデータを文字列形式に変換
        table_data = ""
        for i, table in enumerate(tables):
            table_data += f"\n--- テーブル {i + 1} ---\n"
            table_data += table.df.to_string()

        logger.info(f"抽出データ:\n{table_data}")

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

        # client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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
            company = info.get("company")  # ✅ JSON内の "company" を取得

            # デフォルト値の設定（companyが取得できない場合）
            if not company:
                company = "Unknown"

            log_path = "gpt_feedback_log.csv"
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
                company,  # ✅ company を保存
                "pending"
            ]

            file_exists = os.path.exists(log_path)
            with open(log_path, "a", newline='', encoding='utf-8') as log_file:
                writer = csv.writer(log_file)
                if not file_exists:
                    writer.writerow(["timestamp", "url", "departure", "destination", "input_date", "etd", "eta", "vessel", "feedback"])
                writer.writerow(new_entry)

            return {
                "company": company,  # ✅ JSON内の "company" を返す,
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
        # import logging
        # logger = logging.getLogger(__name__)
        logger.error(f"PyMuPDF解析失敗: {e}")
        return None

    finally:
        try:
            if doc:
                doc.close()
        except:
            pass
        try:
            os.remove("temp_schedule.pdf")
            logger.info("🧹 一時PDFファイルを削除しました。")
        except Exception as e:
            # import logging
            # logger = logging.getLogger(__name__)
            logger.warning(f"[WARN] PDF削除に失敗: {e}")


async def get_pdf_links_from_one(destination_keyword: str) -> list[str]:
    result = None  # 初期化
    try:
        # app/get_pdf_links.py のパスを指定
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

        logger.info(f"[DEBUG] get_pdf_links.py stdout:\n{result.stdout}")
        return json.loads(result.stdout)
    
    except json.JSONDecodeError as je:
        logger.error(f"[ERROR] JSON Decode Error: {je}")
        # result が None でない場合のみ stdout にアクセス
        if result and result.stdout:
            logger.error(f"[DEBUG] 実際の出力内容: {result.stdout}")
        else:
            logger.error("[DEBUG] stdout is None")
        return []
    
    except subprocess.CalledProcessError as cpe:
        logger.error(f"[CalledProcessError] stderr:\n{cpe.stderr}")
        # stdout が存在する場合のみログ出力
        if cpe.stdout:
            logger.error(f"[CalledProcessError] stdout:\n{cpe.stdout}")
        else:
            logger.error("[CalledProcessError] stdout is None")
        return []
    
    except Exception as e:
        logger.error(f"[ERROR] ONE get_pdf_links 実行失敗: {e}")
        return []
    
# COSCOのPDFリンク取得用
async def get_pdf_links_from_cosco(destination_keyword: str) -> list[str]:
    result = None  # 初期化
    try:
        # get_cosco_pdf_links.py のフルパスを指定
        script_path = Path(__file__).resolve().parent / "app" / "get_cosco_pdf_links.py"
        cwd_path = script_path.parent

        result = subprocess.run(
            [sys.executable, str(script_path), destination_keyword, "--silent"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(cwd_path),  # .envが読めるように
            env=os.environ.copy(),  # 現在の環境変数を明示的に渡す（Playwrightの実行にも必要）
        )

        # 正常な場合のみログ出力
        if result.stdout:
            logger.info(f"[COSCO PDFリンク取得] stdout:\n{result.stdout}")

        return json.loads(result.stdout)

    except json.JSONDecodeError as je:
        logger.error(f"[ERROR] JSON Decode Error: {je}")
        # result が None でない場合のみ stdout にアクセス
        if result and result.stdout:
            logger.error(f"[DEBUG] 実際の出力内容: {result.stdout}")
        else:
            logger.error("[DEBUG] stdout is None")
        return []

    except subprocess.CalledProcessError as spe:
        logger.error(f"[ERROR] CalledProcessError: {spe}")
        # stdout と stderr が存在するかを確認してから出力
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
    
# KINKAのPDFリンク取得用
async def get_pdf_links_from_kinka(destination_keyword: str) -> list[str]:
    result = None  # 初期化
    try:
        script_path = Path(__file__).resolve().parent / "app" / "get_kinka_pdf_links.py"
        cwd_path = script_path.parent

        result = subprocess.run(
            [sys.executable, str(script_path), destination_keyword, "--silent"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(cwd_path),  # .envが読めるように
            env=os.environ.copy(),  # 現在の環境変数を明示的に渡す（Playwrightの実行にも必要）
        )

        # 正常な場合のみ stdout をログ出力
        if result.stdout:
            logger.info(f"[KINKA PDFリンク取得] stdout:\n{result.stdout}")
        
        # 出力を JSON としてパース
        return json.loads(result.stdout)

    except json.JSONDecodeError as je:
        logger.error(f"[ERROR] JSON Decode Error: {je}")
        # result が None でない場合のみ stdout を参照
        if result and result.stdout:
            logger.error(f"[DEBUG] 実際の出力内容: {result.stdout}")
        else:
            logger.error("[DEBUG] stdout is None")
        return []
    
    except Exception as e:
        logger.error(f"[ERROR] KINKA get_pdf_links 実行失敗: {e}")
        return []

# ShipmentlinkのPDFリンク取得用
async def get_pdf_links_from_shipmentlink(departure_port: str, destination_port: str) -> list[str]:
    result = None  # 初期化
    try:
        script_path = Path(__file__).resolve().parent / "app" / "get_shipmentlink_pdf_links.py"
        cwd_path = script_path.parent

        result = subprocess.run(
            [sys.executable, str(script_path), departure_port, destination_port, "--silent"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(cwd_path),  # .envが読めるように
            env=os.environ.copy(),  # 現在の環境変数を明示的に渡す（Playwrightの実行にも必要）
        )

        logger.info(f"[Shipmentlink PDF取得] raw stdout:\n{result.stdout}")
        # JSONデコード後、URLデコード
        raw_links = json.loads(result.stdout)
        decoded_links = [unquote(url) for url in raw_links]  # ✅ ここで一括変換
        logger.info(f"[Shipmentlink PDF取得] decoded:\n{decoded_links}")  # ✅ ログに必ず出力！
        
        return decoded_links
    except Exception as e:
        logger.error(f"[Shipmentlink取得失敗] {e}")
        return []

# FastAPI 内の非同期関数
# async def get_schedule_from_maersk(departure: str, destination: str, etd_date: str) -> list[dict]:
#     try:
#         api_key = os.getenv("MAERSK_API_KEY")  # 環境変数から取得
#         if not api_key:
#             raise Exception("MAERSK_API_KEY が未設定です")

#         # UN/LOCODE対応（例: Tokyo -> JP, Los Angeles -> US）
#         ORIGIN_CODE_MAP = {
#             "Tokyo": ("JP", "Tokyo"),
#             "Shanghai": ("CN", "Shanghai")
#         }
#         DEST_CODE_MAP = {
#             "Los Angeles": ("US", "Los Angeles"),
#             "Long Beach": ("US", "Long Beach")
#         }

#         origin_country, origin_city = ORIGIN_CODE_MAP.get(departure, (None, None))
#         dest_country, dest_city = DEST_CODE_MAP.get(destination, (None, None))

#         if not origin_country or not dest_country:
#             raise Exception(f"都市コード未対応: {departure} / {destination}")

#         # APIエンドポイントとパラメータ
#         url = "https://api.maersk.com/products/ocean-products"
#         params = {
#             "vesselOperatorCarrierCode": "MAEU",
#             "collectionOriginCountryCode": origin_country,
#             "collectionOriginCityName": origin_city,
#             "deliveryDestinationCountryCode": dest_country,
#             "deliveryDestinationCityName": dest_city,
#         }

#         headers = {
#             "Consumer-Key": api_key,
#             "Accept": "application/json"
#         }

#         async with httpx.AsyncClient() as client:
#             response = await client.get(url, headers=headers, params=params, timeout=30.0)

#         if response.status_code == 200:
#             data = response.json()

#             # 必要なフィールドのみ抽出して整形
#             # ※下記はサンプル構成で、実際のレスポンスに合わせて調整必要
#             results = []
#             for item in data.get("schedules", []):
#                 results.append({
#                     "vessel": item.get("vesselName"),
#                     "etd": item.get("departureDate"),
#                     "eta": item.get("arrivalDate"),
#                     "service": item.get("serviceName"),
#                 })

#             return results
#         else:
#             logger.warning(f"Maersk APIエラー: {response.status_code} - {response.text}")
#             return []

#     except Exception as e:
#         logger.error(f"[Maersk API取得例外] {str(e)}")
#         return []

# Hapag-Lloydのスケジュール取得関数を追加
# async def get_schedule_from_hapaglloyd(departure: str, destination: str) -> list[dict]:
#     from playwright.async_api import async_playwright
#     results = []
#     try:
#         async with async_playwright() as p:
#             browser = await p.chromium.launch(headless=True)
#             page = await browser.new_page()
#             await page.goto("https://www.hapag-lloyd.com/solutions/schedule/#/", timeout=60000)
#             await page.wait_for_load_state("networkidle")

#             from_input = await page.wait_for_selector('input[aria-label="From"]', timeout=10000)
#             await from_input.fill(departure)
#             await page.wait_for_timeout(500)
#             await page.keyboard.press("ArrowDown")
#             await page.keyboard.press("Enter")

#             to_input = await page.wait_for_selector('input[aria-label="To"]', timeout=10000)
#             await to_input.fill(destination)
#             await page.wait_for_timeout(500)
#             await page.keyboard.press("ArrowDown")
#             await page.keyboard.press("Enter")

#             await page.click('button:has-text("Search")')

#             await page.wait_for_selector('.schedule-table-container', timeout=20000)
#             rows = await page.query_selector_all('.schedule-table-container tbody tr')

#             for row in rows[:3]:
#                 cols = await row.query_selector_all('td')
#                 if len(cols) >= 5:
#                     vessel = await cols[0].inner_text()
#                     etd = await cols[2].inner_text()
#                     eta = await cols[3].inner_text()
#                     results.append({
#                         "company": "Hapag-Lloyd",
#                         "vessel": vessel.strip(),
#                         "etd": etd.strip(),
#                         "eta": eta.strip(),
#                         "fare": "",
#                         "schedule_url": page.url,
#                         "raw_response": f"{vessel.strip()} {etd.strip()}->{eta.strip()}"
#                     })
#             await browser.close()
#     except Exception as e:
#         logger.error(f"[Hapag-Lloyd ERROR] {e}")
#     return results

@app.post("/recommend-shipping")
async def recommend_shipping(req: ShippingRequest):
    logger.info("📦 リクエスト受信:")
    logger.info(f"  Departure Port: {req.departure_port}")
    logger.info(f"  Destination Port: {req.destination_port}")
    logger.info(f"  ETA: {req.etd_date}")
    logger.info(f"  ETD: {req.eta_date}")

    if not req.etd_date and not req.eta_date:
        return {"error": "ETDかETAのいずれかを指定してください。"}

    destination = req.destination_port
    departure = req.departure_port
    keyword = destination
    etd_date = datetime.strptime(req.etd_date, "%Y-%m-%d") if req.etd_date else None
    eta_date = datetime.strptime(req.eta_date, "%Y-%m-%d") if req.eta_date else None

    results = []

    # ========== ONE社 ==========
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
                break  # 最初のマッチで止める

    # ========== COSCO社 ==========
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
                break  # 最初のマッチで止める

# ========== KINKA社（目的地が「上海」の場合のみ） ==========
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
                    break  # 最初のマッチで止める
    else:
        logger.info("📛 KINKA社は『上海』のときのみ検索対象となるため、今回はスキップされました。")

# ========== Shipmentlink社 ========== 
    logger.info(f"🔍 Shipmentlink社 get_pdf_links.py に渡すキーワード: '{keyword}'")
    pdf_urls_shipmentlink = await get_pdf_links_from_shipmentlink(departure, destination)
    
    if not pdf_urls_shipmentlink:
        logger.warning("⚠️ Shipmentlink社のPDFリンク取得に失敗しました。")
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
                result["company"] = "Shipmentlink"
                result["fare"] = str(get_freight_rate(departure, destination, "Shipmentlink")) if not None else "N/A"
                results.append(result)
                logger.info(f"[Shipmentlink社マッチ] {result}")
                success = True
                break  # 最初のマッチで止める
        if not success:
            logger.warning("⚠️ Shipmentlink社のスケジュール抽出に失敗しました。")

    # ========== Maersk社 ========== 
    # maersk_result = await get_schedule_from_maersk(departure, destination, etd_date=req.etd_date)

    # if maersk_result:
    #     for r in maersk_result:
    #         r["company"] = "Maersk"
    #         result["fare"] = get_freight_rate(departure, destination, "Maersk")
    #         results.append(r)
    #     logger.info(f"[Maersk API 成功] {len(maersk_result)} 件取得")

    # ========== Hapag-Lloyd社 ========== 
    # try:
    #     hl_start_date = req.etd_date or req.eta_date
    #     logger.info(f"🔍 Hapag-Lloyd社 スケジュール取得を実行します: {departure} → {destination} | {hl_start_date}")
    #     hl_results = await get_schedule_from_hapaglloyd(departure, destination, hl_start_date)
    #     if hl_results:
    #         results.extend(hl_results)
    #         logger.info(f"[Hapag-Lloyd社マッチ] {hl_results}")
    # except Exception as e:
    #     logger.warning(f"[Hapag-Lloyd社取得失敗] {e}")

    # ========== 結果返却 ==========
    if results:
        logger.info(f"[✅MATCHED] {len(results)}件のスケジュールが見つかりました")
        return results  # ← 配列として返す
    else:
        logger.warning("❌ 全社のいずれにもマッチしませんでした")
        return []  # ← 空のリストで返す（フロントで [] を扱えるようにする）
    

@app.post("/update-feedback")
async def update_feedback(data: FeedbackRequest):
    logger.info(f"フィードバック受信: URL={data.url}, ETD={data.etd}, ETA={data.eta}, Feedback={data.feedback}")
    try:
        with open("gpt_feedback_log.csv", "a", encoding="utf-8", newline='') as f:
            f.write(f'{data.url},{data.etd},{data.eta},{data.feedback}\n')
        return {"message": "フィードバックを記録しました。"}
    except Exception as e:
        logger.exception("フィードバック記録中にエラー")
        raise HTTPException(status_code=500, detail="フィードバックの保存に失敗しました。")

# -------------------------------
# エラーハンドリングミドルウェア
# -------------------------------
@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        # エラーの詳細をログに書く（ファイル・行番号含む）
        error_trace = traceback.format_exc()
        logger.exception("未処理の例外が発生しました:\n%s", error_trace)

        # Swagger上で詳細表示
        return JSONResponse(
            status_code=500,
            content={"detail": error_trace}  # ← エラーの詳細なスタックトレース付き
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)