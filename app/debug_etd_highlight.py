from highlight_etd import highlight_etd_candidates

highlight_etd_candidates(
    pdf_path="temp_schedule.pdf",         # FastAPIで保存されたPDF
    departure="TOKYO",                    # 任意の港（例：YOKOHAMAなどでも可）
    save_path="highlighted_etd.pdf"       # 出力されるPDF名
)
