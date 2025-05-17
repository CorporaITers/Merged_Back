# import sys
# import json
# import logging
# from playwright.sync_api import sync_playwright

# logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
# logger = logging.getLogger(__name__)


# def get_fixed_pdf_link_for_shanghai():
#     url = "https://www.kinka-agency.com/asp/newsitem.asp?nw_id=54"

#     with sync_playwright() as p:
#         browser = p.chromium.launch(headless=True)
#         page = browser.new_page()
#         page.goto(url, timeout=60000)

#         links = page.query_selector_all("a")
#         for link in links:
#             href = link.get_attribute("href")
#             if href and ".pdf" in href:
#                 # 見つけた最初のPDFリンクを返す（基本1件）
#                 full_url = (
#                     f"https://www.kinka-agency.com{href}"
#                     if href.startswith("/")
#                     else f"https://www.kinka-agency.com/{href.lstrip('.')}"
#                 )
#                 logger.info(f"[HASCO PDF検出] href: {full_url}")
#                 browser.close()
#                 return [full_url]

#         browser.close()
#     return []


# if __name__ == "__main__":
#     if len(sys.argv) < 2:
#         print("Usage: python get_kinka_pdf_links.py <destination_keyword>")
#         sys.exit(1)

#     destination_keyword = sys.argv[1].lower()

#     if "上海" in destination_keyword or "shanghai" in destination_keyword:
#         result = get_fixed_pdf_link_for_shanghai()
#         print(json.dumps(result, ensure_ascii=False))
#     else:
#         print("[]")


# 予備コード（BeautifulSoup版）

import sys
import json
import logging
import requests
from bs4 import BeautifulSoup, Tag

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def get_fixed_pdf_link_for_shanghai():
    href = "N/A"  # 初期値を設定
    url = "https://www.kinka-agency.com/asp/newsitem.asp?nw_id=54"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logger.exception("[ERROR] KINKAサイト取得失敗")
        return []

    soup = BeautifulSoup(response.content, "html.parser")
    links = soup.find_all("a", href=True)

    for link in links:
        if isinstance(link, Tag):
            href = link.get("href", "N/A")  # `href` が存在しない場合は "N/A" として扱う
        if isinstance(href, str) and ".pdf" in href:
            full_url = (
                f"https://www.kinka-agency.com{href}"
                if href.startswith("/")
                else f"https://www.kinka-agency.com/{href.lstrip('.')}"
            )
            logger.info(f"[KINKA PDF検出] href: {full_url}")
            return [full_url]

    return []

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python get_kinka_pdf_links.py <destination_keyword>")
        sys.exit(1)

    destination_keyword = sys.argv[1].lower()

    if "上海" in destination_keyword or "shanghai" in destination_keyword:
        result = get_fixed_pdf_link_for_shanghai()
        print(json.dumps(result, ensure_ascii=False))
    else:
        print("[]")
