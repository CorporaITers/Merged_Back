# import sys
# import json
# import os
# import logging
# from dotenv import load_dotenv
# from pathlib import Path

# if os.getenv("OPENAI_API_KEY") is None:
#     from dotenv import load_dotenv
#     dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
#     load_dotenv(dotenv_path)

# # ロガー設定
# logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
# logger = logging.getLogger(__name__)
# logger.info(f"[DEBUG] .env path = {dotenv_path}")
# logger.info(f"[DEBUG] OPENAI_API_KEY = {os.getenv('OPENAI_API_KEY')[:8]}...")

# from openai import OpenAI
# from playwright.sync_api import sync_playwright

# client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
# logger.info("[DEBUG] OpenAI client initialized successfully.")

# region_map = {
#     "NORTH AMERICA EAST COAST": "北米東岸輸出",
#     "NORTH AMERICA WEST COAST": "北米西岸輸出",
#     "HAWAII": "ハワイ輸出",
#     "EUROPE NORTH": "北欧州輸出",
#     "EUROPE MEDITERRANEAN": "地中海輸出",
#     "EAST ASIA": "中国・香港・海峡地・インドネシア輸出",
#     "SOUTHEAST ASIA": "タイ・ベトナム・韓国・台湾・フィリピン輸出",
#     "MIDDLE EAST": "中東・南アジア輸出",
#     "SOUTH AMERICA WEST COAST": "南米西岸輸出",
#     "SOUTH AMERICA EAST COAST": "南米東岸輸出",
#     "AFRICA": "アフリカ輸出",
#     "OCEANIA": "オセアニア輸出",
# }

# def get_region_by_chatgpt(destination_keyword, silent=False):
#     prompt = f"""
# 以下の目的地「{destination_keyword}」は、ONE社の輸出スケジュールPDFのどの地域カテゴリに該当しますか？
# 以下の英語リストから最も適切なものを **1つだけ** 英語で出力してください（他の説明文は不要）：
# ["NORTH AMERICA EAST COAST", "NORTH AMERICA WEST COAST", "HAWAII", "EUROPE NORTH", "EUROPE MEDITERRANEAN", "EAST ASIA", "SOUTHEAST ASIA", "MIDDLE EAST", "SOUTH AMERICA WEST COAST", "SOUTH AMERICA EAST COAST", "AFRICA", "OCEANIA"]
# """
#     try:
#         response = client.chat.completions.create(
#             model="gpt-4o",
#             messages=[{"role": "user", "content": prompt}],
#         )
#         result = response.choices[0].message.content.strip().upper().strip('"')

#         if not silent:
#             logger.info(f"[ChatGPT返答] {result}")

#         if result not in region_map:
#             raise ValueError(f"ChatGPTの返答が不正です: {result}")

#         return region_map[result]
    
#     except Exception as e:
#         logger.exception("[ERROR] ChatGPTによる地域判定で例外:")
#         raise

# # ↓ 手動指定のパス（あなたの環境の1161ビルドを直接指定）
# CHROMIUM_EXECUTABLE_PATH = Path.home() / "AppData/Local/ms-playwright/chromium_headless_shell-1161/chrome-win/headless_shell.exe"

# def get_pdf_links(destination_keyword, silent=False):
#     pdf_links = []
#     region = get_region_by_chatgpt(destination_keyword, silent=silent)

#     if not silent:
#         logger.info(f"[INFO] 判定された日本語PDFカテゴリ: {region}")

#     url = "https://jp.one-line.com/ja/schedules/export"

#     with sync_playwright() as p:
#         browser = p.chromium.launch(
#             headless=True,
#             executable_path=str(CHROMIUM_EXECUTABLE_PATH)  # 明示的にバージョン1161のパスを指定
#         )
#         page = browser.new_page()
#         page.goto(url, timeout=60000)

#         links = page.query_selector_all("a[href$='.pdf']")
#         for link in links:
#             text = link.inner_text().strip()
#             href = link.get_attribute("href")

#             if not silent:
#                 logger.debug(f"[候補] {text}")

#             if region in text and href:
#                 full_url = f"https://jp.one-line.com{href}" if href.startswith("/") else href
#                 pdf_links.append(full_url)

#         browser.close()

#     return pdf_links

# if __name__ == "__main__":
#     try:
#         if len(sys.argv) < 2:
#             logger.error("引数が足りません。")
#             print("[]")
#             sys.exit(1)

#         keyword = sys.argv[1]
#         silent = "--silent" in sys.argv

#         result = get_pdf_links(keyword, silent=silent)
#         print(json.dumps(result, ensure_ascii=False))  # subprocess用出力

#     except Exception as e:
#         logger.exception("[ERROR] get_pdf_links実行中に例外:")
#         print("[]")  # subprocess 側で json.loads に失敗させないため
#         sys.exit(1)


# BeautifulSoup版のコード（予備）

import sys
import json
import os
import logging
from dotenv import load_dotenv
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

# .env 読み込み
dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
load_dotenv(dotenv_path)

# ロガー設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.info(f"[DEBUG] .env path = {dotenv_path}")
logger.info(f"[DEBUG] OPENAI_API_KEY = {os.getenv('OPENAI_API_KEY')[:8]}...")

# OpenAIクライアント初期化
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
logger.info("[DEBUG] OpenAI client initialized successfully.")

# 地域マッピング
region_map = {
    "NORTH AMERICA EAST COAST": "北米東岸輸出",
    "NORTH AMERICA WEST COAST": "北米西岸輸出",
    "HAWAII": "ハワイ輸出",
    "EUROPE NORTH": "北欧州輸出",
    "EUROPE MEDITERRANEAN": "地中海輸出",
    "EAST ASIA": "中国・香港・海峡地・インドネシア輸出",
    "SOUTHEAST ASIA": "タイ・ベトナム・韓国・台湾・フィリピン輸出",
    "MIDDLE EAST": "中東・南アジア輸出",
    "SOUTH AMERICA WEST COAST": "南米西岸輸出",
    "SOUTH AMERICA EAST COAST": "南米東岸輸出",
    "AFRICA": "アフリカ輸出",
    "OCEANIA": "オセアニア輸出",
}

# ChatGPTで地域カテゴリを判定
def get_region_by_chatgpt(destination_keyword, silent=False):
    prompt = f"""
以下の目的地「{destination_keyword}」は、ONE社の輸出スケジュールPDFのどの地域カテゴリに該当しますか？
以下の英語リストから最も適切なものを **1つだけ** 英語で出力してください（他の説明文は不要）：
["NORTH AMERICA EAST COAST", "NORTH AMERICA WEST COAST", "HAWAII", "EUROPE NORTH", "EUROPE MEDITERRANEAN", "EAST ASIA", "SOUTHEAST ASIA", "MIDDLE EAST", "SOUTH AMERICA WEST COAST", "SOUTH AMERICA EAST COAST", "AFRICA", "OCEANIA"]
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
        )
        result = response.choices[0].message.content.strip().upper().strip('"')

        if not silent:
            logger.info(f"[ChatGPT返答] {result}")

        if result not in region_map:
            raise ValueError(f"ChatGPTの返答が不正です: {result}")

        return region_map[result]

    except Exception as e:
        logger.exception("[ERROR] ChatGPTによる地域判定で例外:")
        raise

# PDFリンク取得（BeautifulSoup版）
def get_pdf_links(destination_keyword, silent=False):
    pdf_links = []
    region = get_region_by_chatgpt(destination_keyword, silent=silent)

    if not silent:
        logger.info(f"[INFO] 判定された日本語PDFカテゴリ: {region}")

    url = "https://jp.one-line.com/ja/schedules/export"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logger.exception("[ERROR] requests.get に失敗しました")
        raise

    soup = BeautifulSoup(response.content, "html.parser")
    links = soup.find_all("a", href=True)

    for link in links:
        href = link["href"]
        text = link.get_text(strip=True)

        if href.endswith(".pdf") and region in text:
            full_url = f"https://jp.one-line.com{href}" if href.startswith("/") else href
            pdf_links.append(full_url)
            if not silent:
                logger.info(f"[抽出] {text} -> {full_url}")

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
        print(json.dumps(result, ensure_ascii=False))  # subprocess用出力

    except Exception as e:
        logger.exception("[ERROR] get_pdf_links実行中に例外:")
        print("[]")  # subprocess 側で json.loads に失敗させないため
        sys.exit(1)
