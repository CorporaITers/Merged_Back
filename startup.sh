# #!/bin/bash

# # OCRツールのインストール（3回までリトライ）
# for i in 1 2 3; do
#   apt-get update && \
#   apt-get install -y --fix-missing -o Acquire::http::No-Cache=true \
#     poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-jpn && break || sleep 10
# done

# # Python依存ライブラリのインストール
# python -m pip install --upgrade pip
# python -m pip install -r requirements.txt

# # FastAPIアプリの起動
# gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000 --timeout 120
