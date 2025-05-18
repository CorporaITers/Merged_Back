import sys
import json
import os
import logging
from dotenv import load_dotenv
from pathlib import Path
from openai import AzureOpenAI
import re

# if os.getenv("OPENAI_API_KEY") is None:
#     from dotenv import load_dotenv
#     dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
#     load_dotenv(dotenv_path)

# ✅ まず dotenv_path を定義
dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
load_dotenv(dotenv_path, override=True)

# ログ設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.info(f"[DEBUG] .env path = {dotenv_path}")
api_key = os.getenv('OPENAI_API_KEY')
logger.info(f"[DEBUG] OPENAI_API_KEY = {api_key[:8]}..." if api_key else "[DEBUG] OPENAI_API_KEY is not set.")

# client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
# OpenAIクライアント初期化
client = AzureOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    api_version=os.getenv("OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("OPENAI_API_BASE") or ""
)

logger.info("[DEBUG] OpenAI client initialized successfully.")

# 地域マッピング（日付部分をワイルドカード化）
region_map = {
    "AMERICA CANADA": [
        "アメリカ・カナダサービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/EXP_USA.pdf"]
    ],
    "AUSTRALIA": [
        "オーストラリアサービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/EXP_AUS.pdf"]
    ],
    "NEW ZEALAND": [
        "ニュージーランドサービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/EXP_NZ.pdf"]
    ],
    "EUROPE": [
        "ヨーロッパサービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/EXP_EU.pdf"]
    ],
    "MEDITERRANEAN": [
        "地中海サービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/EXP_MED.pdf"]
    ],
    "RED SEA": [
        "紅海サービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_RED.pdf"]
    ],
    "MIDDLE EAST": [
        "中近東サービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_PG.pdf"]
    ],
    "SOUTH AMERICA": [
        "南米東岸・西岸サービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_SOUTH_AMERICA.pdf"]
    ],
    "AFRICA": [
        "アフリカサービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/EXP_Africa.pdf"]
    ],
    "KOREA": [
        "韓国（釜山）向けサービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_kor.pdf"]
    ],
    "SOUTH EAST ASIA": [
        "タイ・ベトナム向け直行サービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_s_asia_direct_new_1.pdf"]
    ],
    "MALAYSIA SINGAPORE INDONESIA": [
        "シンガポール・マレーシア・インドネシア向け直行サービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_s_asia_direct_new_2.pdf"]
    ],
    "SOUTH ASIA": [
        "東南アジア・南アジア向けサービス・シンガポール経由", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_s_asia_direct_new_3.pdf"]
    ],
    "CHINA FEEDER": [
        "上海・長江流域フィーダーサービス", 
        [
            "https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_sha_chanjiang_1.pdf",
            "https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_sha_chanjiang_2.pdf"
        ]
    ],
    "NINGBO WENZHOU": [
        "寧波・温州サービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_nbo.pdf"]
    ],
    "QINGDAO LIANYUNGANG": [
        "青島・連雲港サービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_qin_lyg.pdf"]
    ],
    "XINGANG DALIAN YINGKOU": [
        "新港・大連・営口サービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_dal_xtg.pdf"]
    ],
    "HONGKONG PEARL": [
        "香港・南中国及びパールリバーデルタサービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_schina_jcv.pdf"]
    ],
    "TAIWAN": [
        "台湾サービス", 
        ["https://world.lines.coscoshipping.com/lines_resource/local/japan/defaultContentAttachment/{DATE}/exp_tw.pdf"]
    ]
}

def get_region_by_chatgpt(destination_keyword, silent=False):
    """ ChatGPTを用いて地域カテゴリを判定 """
    prompt = f"""
以下の目的地「{destination_keyword}」は、COSCO社の輸出スケジュールPDFのどの地域カテゴリに該当しますか？
以下の英語リストから最も適切なものを **1つだけ** 英語で出力してください（他の説明文は不要）：
["AMERICA CANADA", "AUSTRALIA", "NEW ZEALAND", "EUROPE", "MEDITERRANEAN", "RED SEA", "MIDDLE EAST", "SOUTH AMERICA", "AFRICA", "KOREA", "SOUTH EAST ASIA", "MALAYSIA SINGAPORE INDONESIA", "SOUTH ASIA", "CHINA FEEDER", "NINGBO WENZHOU", "QINGDAO LIANYUNGANG", "XINGANG DALIAN YINGKOU", "HONGKONG PEARL", "TAIWAN"]
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )

        content = response.choices[0].message.content
        if content is None:
            raise ValueError("ChatGPTの返答が空です")
        result = content.strip().upper().strip('"')

        if not silent:
            logger.info(f"[ChatGPT返答] {result}")

        if result not in region_map:
            raise ValueError(f"[ERROR] 不正な地域カテゴリ: {result}")

        return result
    
    except Exception as e:
        logger.exception("[ERROR] ChatGPTによる地域判定に失敗")
        raise

    # result = response.choices[0].message.content.strip()
    # logger.info(f"[ChatGPT日本語カテゴリ名 判定結果] → '{result}'")

    # return result

# def normalize_text(s: str) -> str:
#     return normalize('NFKC', s).replace(' ', '').replace('　', '').lower()

def get_pdf_links(destination_keyword, silent=False):
    pdf_links = []
    region_key = get_region_by_chatgpt(destination_keyword, silent=silent)
    region_info = region_map.get(region_key)

    if not region_info:
        logger.warning(f"[WARNING] 地域カテゴリ '{region_key}' は無効です。")
        return []

    region_name, pdf_patterns = region_info

    # URL内の日付部分をワイルドカードとして扱う
    date_pattern = r"/(\d{8})/"
    for pattern in pdf_patterns:
        # 日付部分を削除した比較用URLを生成
        base_url = re.sub(date_pattern, "/{DATE}/", pattern)
        logger.info(f"[INFO] 照合用URLパターン: {base_url}")

        # 実際のPDFリンクを生成
        for date_part in ["20250507", "20250508", "20250509"]:
            pdf_url = base_url.replace("{DATE}", date_part)
            pdf_links.append(pdf_url)
            logger.info(f"[抽出] {pdf_url}")

    return pdf_links

# エントリポイント
if __name__ == "__main__":
    try:
        if len(sys.argv) < 2:
            logger.error("引数が足りません。")
            print("[]")
            sys.exit(1)

        keyword = sys.argv[1]
        silent = "--silent" in sys.argv

        result = get_pdf_links(keyword, silent=silent)
        print(json.dumps(result, ensure_ascii=False))

    except Exception as e:
        logger.exception("[ERROR] get_pdf_links実行中に例外:")
        print("[]")
        sys.exit(1)


# BeautifulSoup版のコード（予備）

# import sys
# import json
# import os
# import logging
# from dotenv import load_dotenv
# from unicodedata import normalize
# from pathlib import Path
# import requests
# from bs4 import BeautifulSoup
# from openai import OpenAI

# # .env 読み込み
# dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
# load_dotenv(dotenv_path)

# # ログ設定
# logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
# logger = logging.getLogger(__name__)
# logger.info(f"[DEBUG] .env path = {dotenv_path}")
# logger.info(f"[DEBUG] OPENAI_API_KEY = {os.getenv('OPENAI_API_KEY')[:8]}...")

# # OpenAIクライアント
# client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# region_map = {
#     # 洋主要基幹航路
#     "AMERICA CANADA": "アメリカ・カナダサービス",
#     "AUSTRALIA": "オーストラリアサービス",
#     "NEW ZEALAND": "ニュージーランドサービス",
#     "EUROPE": "ヨーロッパサービス",
#     "MEDITERRANEAN": "地中海サービス",
#     "RED SEA": "紅海サービス",
#     "MIDDLE EAST": "中東サービス",
#     "SOUTH AMERICA": "南米東岸・西岸サービス",
#     "AFRICA": "アフリカサービス",

#     # 東南アジア・南アジア
#     "KOREA": "韓国（釜山）向けサービス",
#     "SOUTH EAST ASIA": "タイ・ベトナム向け直行サービス",
#     "MALAYSIA SINGAPORE INDONESIA": "シンガポール・マレーシア・インドネシア直行サービス",
#     "SOUTH ASIA": "インド・スリランカ向けサービス（上海経由）",

#     # 中国・台湾
#     "CHINA FEEDER": "長江流域フィーダーサービス",
#     "NINGBO WENZHOU": "寧波・温州サービス",
#     "QINGDAO LIANYUNGANG": "青島・連雲港サービス",
#     "XINGANG DALIAN YINGKOU": "新港・大連・営口・威海サービス",
#     "HONGKONG PEARL": "香港・南中国パールリバーサービス",
#     "TAIWAN": "台湾サービス（KTX1 / KTX3）"
# }

# def get_region_by_chatgpt(destination_keyword: str, silent=False):
#     prompt = f"""
# # あなたは国際物流に詳しいアシスタントです。

# # 以下の目的地「{destination_keyword}」が、COSCO社スケジュールページ（https://world.lines.coscoshipping.com/japan/jp/services/localschedule/1/1）の**輸出**欄に掲載されているカテゴリのうち、どれに該当するかを判断してください。

# # 次のリストから最も適切なカテゴリを1つ選び、**その英語キー（大文字）だけを1行で出力**してください。説明や記号は不要です。

# # ["AMERICA CANADA", "AUSTRALIA", "NEW ZEALAND", "EUROPE", "MEDITERRANEAN", "RED SEA", "MIDDLE EAST", "SOUTH AMERICA", "AFRICA", "KOREA", "SOUTH EAST ASIA", "MALAYSIA SINGAPORE INDONESIA", "SOUTH ASIA", "CHINA FEEDER", "NINGBO WENZHOU", "QINGDAO LIANYUNGANG", "XINGANG DALIAN YINGKOU", "HONGKONG PEARL", "TAIWAN"]
# """

#     try:
#         response = client.chat.completions.create(
#             model="gpt-4o",
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0
#         )
#         result = response.choices[0].message.content.strip().upper()

#         if not silent:
#             logger.info(f"[ChatGPT返答] {result}")

#         if result not in region_map:
#             raise ValueError(f"ChatGPTの返答が不正です: {result}")

#         return region_map[result]

#     except Exception as e:
#         logger.exception("[ERROR] ChatGPTによる地域判定失敗")
#         raise

# def normalize_text(s: str) -> str:
#     return normalize('NFKC', s).replace(' ', '').replace('　', '').lower()

# def get_pdf_links(destination_keyword, silent=False):
#     pdf_links = []
#     region_jp = get_region_by_chatgpt(destination_keyword, silent=silent)

#     if not silent:
#         logger.info(f"[INFO] ChatGPTにより得られた日本語カテゴリ名: {region_jp}")

#     url = "https://world.lines.coscoshipping.com/japan/jp/services/localschedule/1/1"
#     headers = {"User-Agent": "Mozilla/5.0"}

#     try:
#         response = requests.get(url, headers=headers, timeout=10)
#         response.raise_for_status()
#     except Exception as e:
#         logger.exception("[ERROR] requests.get に失敗しました")
#         raise

#     # ✅ レスポンスHTMLをデバッグ用に保存
#     with open("cosco_debug.html", "wb") as f:
#         f.write(response.content)
#         logger.info("[DEBUG] COSCOページHTMLを cosco_debug.html に保存しました")

#     soup = BeautifulSoup(response.content, "html.parser")
#     links = soup.find_all("a", href=True)

#     for link in links:
#         text = link.get_text(strip=True)
#         href = link["href"]

#         # if (
#         #     href.endswith(".pdf")
#         #     and ("輸出" in text or "exp" in href.lower())
#         #     and normalize_text(region_jp) in normalize_text(text)
#         # ):
#         #     full_url = f"https://world.lines.coscoshipping.com{href}" if href.startswith("/") else href
#         #     pdf_links.append(full_url)
#         #     if not silent:
#         #         logger.info(f"[MATCH] {text} → {full_url}")

#         # if href.endswith(".pdf"):
#         #     full_url = f"https://world.lines.coscoshipping.com{href}" if href.startswith("/") else href
#         #     logger.info(f"[DEBUG MATCH] {text} → {full_url}")
#         #     pdf_links.append(full_url)
#         logger.debug(f"[候補] text: {text}, href: {href}")
#         logger.debug(f"[比較] region='{normalize_text(region_jp)}' in '{normalize_text(text)}'")
        
#         if href.endswith(".pdf"):
#             full_url = f"https://world.lines.coscoshipping.com{href}" if href.startswith("/") else href
#             logger.info(f"[全PDF候補] {text} → {full_url}")
#             pdf_links.append(full_url)

#     return pdf_links

# if __name__ == "__main__":
#     try:
#         if len(sys.argv) < 2:
#             logger.error("❌ 実行引数が不足しています。使用例: python get_cosco_pdf_links.py Los Angeles")
#             print("[]")
#             sys.exit(1)

#         keyword = sys.argv[1]
#         silent = "--silent" in sys.argv

#         result = get_pdf_links(keyword, silent=silent)
#         print(json.dumps(result, ensure_ascii=False))  # subprocess用出力

#     except Exception as e:
#         logger.exception("[ERROR] get_cosco_pdf_links実行中に例外:")
#         print("[]")
#         sys.exit(1)