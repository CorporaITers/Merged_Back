
import fitz  # PyMuPDF
from dateutil import parser
import os

def highlight_etd_candidates(pdf_path: str, departure: str = "TOKYO", save_path: str = "highlighted_etd.pdf"):
    # 出発地とマッチするキーワード（必要に応じて増やす）
    departure_aliases = [departure.upper(), departure.capitalize(), departure.lower()]

    # 開く
    doc = fitz.open(pdf_path)

    port_x_departure = None

    # 出発地の列の x 座標を検出
    for page in doc:
        words = page.get_text("words")
        for w in words:
            for alias in departure_aliases:
                if alias in w[4]:
                    port_x_departure = w[0]
                    print(f"[INFO] '{departure}' column found at x={port_x_departure}")
                    break
            if port_x_departure:
                break
        if port_x_departure:
            break

    if not port_x_departure:
        print("[ERROR] 出発地の列が見つかりませんでした。")
        return

    # ETD候補に矩形描画（±5の範囲）
    for page_number, page in enumerate(doc):
        words = page.get_text("words")
        for w in words:
            try:
                # x 座標が一致する列にある単語が日付として解釈できるか
                if abs(w[0] - port_x_departure) < 5:
                    parser.parse(w[4])  # 日付として解釈できるかだけチェック
                    rect = fitz.Rect(w[0], w[1], w[2], w[3])
                    highlight = page.add_rect_annot(rect)
                    highlight.set_colors(stroke=(1, 0, 0))  # 赤枠
                    highlight.update()
                    print(f"[HIGHLIGHT] Page {page_number + 1}: '{w[4]}' @ x={w[0]:.2f}, y={w[1]:.2f}")
            except:
                continue

    # 保存
    doc.save(save_path)
    doc.close()
    print(f"[DONE] ハイライト付きPDFを保存しました: {save_path}")
