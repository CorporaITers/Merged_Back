# #!/bin/bash

# # カスタムビルドコマンド
# echo "Custom deployment script running..."

# # Python依存関係のインストール
# pip install -r requirements.txt

# # システムパッケージのインストール（権限がある場合）
# if [ "$WEBSITE_INSTANCE_ID" ]; then
#     echo "Installing system packages..."
#     apt-get update
#     apt-get install -y tesseract-ocr tesseract-ocr-jpn poppler-utils
# fi

# echo "Deployment completed."