import sys
import json
import asyncio
import logging
from datetime import datetime
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # 手動突破のためヘッドあり
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://www.hapag-lloyd.com/solutions/schedule/#/")
        print("✅ CAPTCHAを手動で突破してください。突破後にEnterキーを押すと保存されます。")
        input("➡ CAPTCHA突破後、Enterを押してください...")
        await context.storage_state(path="hapag_state.json")  # セッション保存
        print("✅ セッションを保存しました！")
        await browser.close()

asyncio.run(run())

async def get_hapaglloyd_schedule(departure: str, destination: str, start_date: str = None) -> list[dict]:
    results = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(storage_state="hapag_state.json")
            page = await browser.new_page()
            logger.info("🌐 Hapag-Lloyd スケジュールページに移動中...")
            await page.goto("https://www.hapag-lloyd.com/solutions/schedule/#/", timeout=60000)
            await page.wait_for_selector('input[placeholder*="Location name or code"]', timeout=30000)
            await page.wait_for_timeout(2000)  # ページが完全に描画されるのを少し待つ
            await page.screenshot(path="debug_loaded.png")

            # 入力欄（Start / End Location）取得
            inputs = await page.query_selector_all('input[placeholder*="Location name or code"]')
            if len(inputs) < 2:
                logger.error("❌ 出発地・到着地の入力欄が見つかりません")
                return []

            from_input, to_input = inputs[0], inputs[1]

            # 出発地入力
            logger.info(f"📍 出発地: {departure}")
            await from_input.click()
            await from_input.fill(departure)
            await page.wait_for_timeout(1000)
            await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter")

            # 到着地入力
            logger.info(f"📍 到着地: {destination}")
            await to_input.click()
            await to_input.fill(destination)
            await page.wait_for_timeout(1000)
            await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter")

            # 出発日入力（任意）
            if start_date:
                logger.info(f"📅 出発日: {start_date}")
                date_input = await page.query_selector('input[type="date"]')
                if date_input:
                    await date_input.fill(start_date)
                    await page.wait_for_timeout(500)

            # Findボタンをクリック
            logger.info("🔍 検索を実行")
            await page.click('button:has-text("Find")')

            # 結果待機
            try:
                await page.wait_for_selector('.schedule-table-container', timeout=20000)
                logger.info("✅ 結果が表示されました")
            except:
                await page.screenshot(path="debug_no_result.png")
                logger.warning("❌ 結果が表示されませんでした")
                return []

            # 結果の抽出（最大3件）
            rows = await page.query_selector_all('.schedule-table-container tbody tr')
            for row in rows[:3]:
                cols = await row.query_selector_all('td')
                if len(cols) >= 5:
                    vessel = await cols[0].inner_text()
                    etd = await cols[2].inner_text()
                    eta = await cols[3].inner_text()
                    results.append({
                        "company": "Hapag-Lloyd",
                        "vessel": vessel.strip(),
                        "etd": etd.strip(),
                        "eta": eta.strip(),
                        "schedule_url": page.url
                    })

            await browser.close()
    except Exception as e:
        logger.error(f"[ERROR] {e}")
        try:
            await page.screenshot(path="debug_exception.png")
        except:
            logger.warning("⚠️ スクリーンショット撮影失敗")
        return []

    return results

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python get_hapaglloyd_schedule.py <departure> <destination> [<start_date>]")
        sys.exit(1)

    departure = sys.argv[1]
    destination = sys.argv[2]
    start_date = sys.argv[3] if len(sys.argv) >= 4 else datetime.today().strftime("%Y-%m-%d")

    try:
        result = asyncio.run(get_hapaglloyd_schedule(departure, destination, start_date))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.error(f"[ERROR] {e}")
        print("[]")
