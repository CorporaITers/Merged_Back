import sys
import json
import os
import logging
from dotenv import load_dotenv
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import re

# .env 読み込み
if os.getenv("OPENAI_API_KEY") is None:
    from dotenv import load_dotenv
    dotenv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
    load_dotenv(dotenv_path)

# ログ設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 出発港 → locコードマッピング
departure_port_map = {
    "Tokyo": "JPTYO",
    "Yokohama": "JPYOK",
    "Osaka": "JPOSA",
    "Nagoya": "JPNGY",
    "Kobe": "JPUKB",
    # 必要に応じて追加
}

# ChatGPTの地域分類 → Shipmentlink表示用カテゴリ名（最適化版）
destination_region_map = {
    "NORTH AMERICA": ["North America & Canada", "北米"],
    "CENTRAL AMERICA": ["Panama, Caribbean Sea", "中南米"],
    "SOUTH AMERICA": ["South Africa, East Coast Of South America, Mauritius", "南米東岸", "ブラジル"],
    "EUROPE": ["Europe", "欧州"],
    "OCEANIA": ["Oceania", "オセアニア", "Australia"],
    "SOUTHEAST ASIA": ["Southeast Asia", "東南アジア"],
    "INDIAN SUBCONTINENT": ["Indian Sub-Continent", "インド周辺", "インド", "スリランカ", "パキスタン"],
    "CHINA": ["China", "中国", "上海", "厦門"],
    "TAIWAN": ["Taiwan", "台湾"],
    "HONG KONG": ["Hong Kong", "香港"],
    "KOREA": ["Korea", "韓国"],
    "MIDDLE EAST": ["Arabian Persian Gulf", "中近東", "ペルシャ湾"],
    "AFRICA": ["South Africa", "アフリカ", "モーリシャス"]
}

def get_region_by_chatgpt(destination_keyword: str, silent=False):
    prompt = f"""
次の目的地「{destination_keyword}」が、Shipmentlink社のスケジュール表示ページで使われるカテゴリのどれに該当しますか？
以下から英語1単語で出力してください（他の文は不要）：

["NORTH AMERICA", "CENTRAL AMERICA", "SOUTH AMERICA", "EUROPE", "OCEANIA", "SOUTHEAST ASIA", "INDIAN SUBCONTINENT", "CHINA", "TAIWAN", "HONG KONG", "KOREA", "MIDDLE EAST", "AFRICA"]
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        result = response.choices[0].message.content.strip().upper().strip('"')
        if result not in destination_region_map:
            raise ValueError(f"ChatGPTの返答が不正です: {result}")
        if not silent:
            logger.info(f"[ChatGPT地域判定] {result} → {destination_region_map[result]}")
        return destination_region_map[result]
    except Exception as e:
        logger.exception("ChatGPT地域判定で失敗しました")
        raise


def get_pdf_links(departure_port: str, destination_port: str, silent=False):
    dep_code = departure_port_map.get(departure_port.title())
    if not dep_code:
        logger.error(f"出発港 '{departure_port}' に対応するコードが見つかりません")
        return []

    region_name = get_region_by_chatgpt(destination_port, silent=silent)
    url_initial = 'https://www.shipmentlink.com/jp/tvs2/jsp/TVS2_ViewSchedule.jsp?loc='
    url_result = 'https://www.shipmentlink.com/loc/tvs2/jsp/TVS2_ViewScheduleResult.jsp'

    session = requests.Session()
    session.get(url_initial)

    params = {
        'loc': dep_code,
        'type': 'O',
        'ctry': 'JP',
        'lang': 'jp',
        'pick_loc': 'Y'
    }

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        'Referer': url_initial,
        'Origin': 'https://www.shipmentlink.com'
    }

    response = session.get(url_result, params=params, headers=headers)
    logger.info(f"[DEBUG] HTTP status: {response.status_code}")
    soup = BeautifulSoup(response.text, "html.parser")

    pdf_links = []

    for link in soup.find_all("a", href=True):
        text = link.get_text(strip=True)
        href = link.get("href", "")
    
        # 正規化処理：GoWin形式や相対パスを含むPDFリンクを正しく変換
        match = re.search(r"GoWin\('(.+?\.pdf)'\)", href)
        if match:
            pdf_path = match.group(1)
            full_url = f"https://www.shipmentlink.com{pdf_path}"
        elif href.lower().endswith(".pdf"):
            full_url = "https://www.shipmentlink.com" + href if href.startswith("/") else href
        else:
            continue  # PDFでない場合スキップ
    
        # ▼ 英語でも日本語でもマッチさせる
        normalized_text = text.lower()
        normalized_dest = destination_port.lower()
        # region_nameが list であればそれぞれをマッチ
        if isinstance(region_name, list):
            match_found = any(keyword.lower() in normalized_text for keyword in region_name)
        else:
            match_found = region_name.lower() in normalized_text

        if normalized_dest in normalized_text or match_found:
            pdf_links.append(full_url)
            if not silent:
                logger.info(f"[PDFリンク検出] {text} → {full_url}")

    return pdf_links

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python get_shipmentlink_pdf_links.py <departure> <destination> [--silent]")
        sys.exit(1)

    departure = sys.argv[1]
    destination = sys.argv[2]
    silent = "--silent" in sys.argv

    try:
        result = get_pdf_links(departure, destination, silent=silent)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        logger.exception("[ERROR] Shipmentlink PDF取得失敗")
        print("[]")
        sys.exit(1)
