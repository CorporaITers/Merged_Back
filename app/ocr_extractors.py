# ocr_extractors.py
import re
import logging
from typing import Dict, Any, Tuple, List

# ロギング設定
logger = logging.getLogger(__name__)

def identify_po_format(ocr_text: str) -> Tuple[str, float]:
    """
    OCRで抽出したテキストからPOフォーマットを識別します
    
    :param ocr_text: OCRで抽出したテキスト
    :return: (フォーマット名, 信頼度)
    """
    # フォーマット判定のための特徴と重み
    format_features = {
        "format1": [
            (r"\(Buyer(?:'|')s Info\)", 10),  # 最も重要な特徴
            (r"ABC Company", 5),
            (r"Purchase Order:?\s*\d+", 5),
            (r"Ship to:", 3),
            (r"Unit Price:?\s*\$", 3),
            (r"EXT Price:", 3),
            (r"Inco Terms:", 2),
            (r"Del Date:", 2)
        ],
        "format2": [
            (r"Purchase Order\s*$", 10),  # 最も重要な特徴
            (r"Supplier:", 5),
            (r"Purchase Order no:?\s*\d+", 5),
            (r"Payment Terms:", 3),
            (r"Incoterms:", 3),
            (r"Discharge Port:", 3),
            (r"Buyer:", 3),
            (r"Commodity", 2),
            (r"Grand Total", 2)
        ],
        "format3": [
            (r"(?:\/\/\/|///)ORDER CONFIMATION(?:\/\/\/|///)", 10),  # 最も重要な特徴
            (r"Contract Party\s*:", 5),
            (r"Order No\.", 5),
            (r"Grade [A-Z]", 3),
            (r"Qt'y \(mt\)", 3), 
            (r"PORT OF DISCHARGE", 3),
            (r"Payment term", 2),
            (r"TIME OF SHIPMENT", 2),
            (r"PORT OF LOADING", 2)
        ]
    }
    
    # 各フォーマットの一致スコアを計算
    format_scores = {}
    for format_name, features in format_features.items():
        score = 0
        for pattern, weight in features:
            if re.search(pattern, ocr_text, re.IGNORECASE):
                score += weight
        format_scores[format_name] = score
    
    # 最も高いスコアのフォーマットを選択
    if all(score == 0 for score in format_scores.values()):
        # すべてのスコアが0の場合、フォーマット不明
        return "unknown", 0.0
    
    # 合計スコアを計算して信頼度を算出
    best_format = "unknown"  # デフォルト値を設定
    if isinstance(format_scores, dict) and all(isinstance(v, (int, float)) for v in format_scores.values()):
        # 最大スコアのフォーマットを取得
        best_format = max(format_scores, key=lambda k: format_scores[k])
    
        # 指定されたフォーマットが format_features に存在するか確認
        if best_format in format_features:
            total_possible_score = sum(weight for _, weight in format_features[best_format])
        else:
            total_possible_score = 0
    
        confidence = format_scores[best_format] / total_possible_score if total_possible_score > 0 else 0
    else:
        confidence = 0

    logger.info(f"識別したPOフォーマット: {best_format}, 信頼度: {confidence:.2f}, スコア: {format_scores}")
    return best_format, confidence

def extract_field_by_regex(ocr_text: str, patterns: List[str], default_value: str = "") -> str:
    """
    正規表現パターンリストを使用して、最初にマッチするフィールド値を抽出します
    
    :param ocr_text: OCRで抽出したテキスト
    :param patterns: 正規表現パターンのリスト
    :param default_value: デフォルト値
    :return: 抽出された値または空文字列
    """
    for pattern in patterns:
        match = re.search(pattern, ocr_text, re.IGNORECASE | re.MULTILINE)
        if match and match.group(1).strip():
            value = match.group(1).strip()
            # 余計な記号を削除
            value = re.sub(r'^[:\s]+|[:\s]+$', '', value)
            return value
    return default_value

def extract_format1_data(ocr_text: str) -> Dict[str, Any]:
    """
    フォーマット1（Buyer's Info）からデータを抽出します
    
    :param ocr_text: OCRで抽出したテキスト
    :return: 構造化されたデータ
    """

    result = {
        "customer": "",
        "poNumber": "",
        "currency": "",
        "products": [],
        "totalAmount": "",
        "paymentTerms": "",
        "terms": "",
        "destination": ""
    }
    
# 顧客名の抽出（Buyer’s Info ブロックを直接パース）
    customer_block = re.search(
        r"\(Buyer[’']s Info\)\s*\n+(.*?)(?:\n{2,}|Purchase Order|Address:|Ship to:)",
        ocr_text,
        re.IGNORECASE | re.DOTALL
    )

    if customer_block:
        customer_lines = customer_block.group(1).split("\n")
        cleaned_lines = [
            line.strip() for line in customer_lines
            if line.strip()
            and not re.search(r'^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]*\d{1,2},\s*\d{4}$', line, re.IGNORECASE)  # 日付形式完全一致
            and not re.search(r'\d{1,2},\s*\d{4}', line)  # 21, 2025 形式も排除
            and not re.search(r'@|email|address|phone|fax|order|ship to', line, re.IGNORECASE)
        ]
        company_line = next(
            (line for line in cleaned_lines if re.search(r'(Company|Co\.|Ltd\.|Inc\.|LLC|Corp\.|Corporation|Limited)', line)),
            None
        )
        result["customer"] = company_line or (cleaned_lines[0] if cleaned_lines else "")
    else:
        # フォールバック
        result["customer"] = extract_field_by_regex(ocr_text, [
            r"Buyer[’']s Info.*?([A-Za-z0-9\s&.,\-]+(?:Company|Co\.?|Ltd\.?|Inc\.?|Corporation|LLC|Limited))"
        ])
    
    # PO番号の抽出
    result["poNumber"] = extract_field_by_regex(ocr_text, [
        r"Purchase Order(?::|Order|Number)?:?\s*(\d+)",
        r"(?:PO|Order)(?:\s+No)?\.?:?\s*(\d+)"
    ])
    
    # 通貨の抽出
    currency_match = re.search(r"(USD|EUR|JPY|CNY)", ocr_text)
    if currency_match:
        result["currency"] = currency_match.group(1)
    
    # 製品情報の抽出
    product_name = extract_field_by_regex(ocr_text, [
        r"Item:\s*(.*?)(?:\n|$)",
        r"Product:?\s*(.*?)(?:\n|Quantity)"
    ])
    
    quantity = extract_field_by_regex(ocr_text, [
        r"Quantity:\s*([\d,.]+)\s*(?:KG|kg|MT|mt)",
        r"Qty:?\s*([\d,.]+)\s*(?:KG|kg|MT|mt)"
    ])
    
    unit_price = extract_field_by_regex(ocr_text, [
        r"Unit Price:\s*\$?\s*([\d,.]+)",
        r"Unit Price:.*?per\s*.*?\$?\s*([\d,.]+)"
    ])
    
    amount = extract_field_by_regex(ocr_text, [
        r"EXT Price:\s*([\d,.]+)",
        r"Amount:\s*([\d,.]+)"
    ])

    # カンマを削除する処理を追加
    if quantity:
        quantity = quantity.replace(',', '')  # 数量のカンマ削除
    if unit_price:
        unit_price = unit_price.replace(',', '')  # 単価のカンマ削除
    if amount:
        amount = amount.replace(',', '')  # 金額のカンマ削除

    if product_name:
        result["products"].append({
            "name": product_name,
            "quantity": quantity,
            "unitPrice": unit_price,
            "amount": amount
        })
    
    # 合計金額の抽出
    result["totalAmount"] = extract_field_by_regex(ocr_text, [
        r"TOTAL\s*([\d,.]+)",
        r"Total:?\s*([\d,.]+)"
    ])
    
    # 支払条件の抽出
    result["paymentTerms"] = extract_field_by_regex(ocr_text, [
        r"Terms:\s*(.*?)(?:\n|$)",
        r"Payment terms?:?\s*(.*?)(?:\n|$)",
        r"Net Due within\s*(.*?)(?:\n|$)"
    ])
    
    # 出荷条件の抽出
    result["terms"] = extract_field_by_regex(ocr_text, [
        r"Inco Terms:\s*(.*?)(?:\n|$)",
        r"Shipping Terms:\s*(.*?)(?:\n|$)",
        r"Delivery Terms:\s*(.*?)(?:\n|$)"
    ])
    
    # 配送先の抽出（emailなどの文字列を除外）
    destination = extract_field_by_regex(ocr_text, [
        r"Ship to:\s*(.*?)(?:\n|$)",
        r"Delivery Address:\s*(.*?)(?:\n|$)"
    ])
    # emailアドレスらしき文字列を除去
    if "@" in destination or "email" in destination.lower():
        destination = ""
    result["destination"] = destination

    
    return result

def extract_format2_data(ocr_text: str) -> Dict[str, Any]:
    """
    フォーマット2（Purchase Order top line）からデータを抽出します
    
    :param ocr_text: OCRで抽出したテキスト
    :return: 構造化されたデータ
    """
    result = {
        "customer": "",
        "poNumber": "",
        "currency": "",
        "products": [],
        "totalAmount": "",
        "paymentTerms": "",
        "terms": "",
        "destination": ""
    }
    
    # 顧客名（購入者）の抽出
    result["customer"] = extract_field_by_regex(ocr_text, [
        r"Buyer:\s*(.*?)(?:\n|$)",
        r"(?:Buyer|Customer|Client):\s*(.*?)(?:\n|$)"
    ])
    
    # PO番号の抽出
    result["poNumber"] = extract_field_by_regex(ocr_text, [
        r"Purchase Order no:?\s*(\d+)",
        r"PO (?:number|no\.?):\s*(\d+)"
    ])
    
    # 通貨の抽出
    currency_match = re.search(r"(USD|EUR|JPY|CNY)", ocr_text)
    if currency_match:
        result["currency"] = currency_match.group(1)
    
    # 製品情報の抽出 - フォーマット2は複数製品の可能性が高い
    # 表形式データの抽出
    product_rows = re.findall(r"([A-Za-z0-9]+)\s+(Product [A-Za-z])\s+([\d,]+)\s*kg\s+US\$?([\d.]+)\s+US\$?([\d,.]+)", ocr_text)
    
    if product_rows:
        for _, name, quantity, unit_price, amount in product_rows:
            result["products"].append({
                "name": name.strip(),
                "quantity": quantity.strip(),
                "unitPrice": unit_price.strip(),
                "amount": amount.strip()
            })
    else:
        # 表形式でない場合は別の方法で抽出
        product_sections = re.findall(r"(Product [A-Za-z])[^\n]*\n[^\n]*?([\d,]+)\s*kg[^\n]*?(US\$[\d.]+)[^\n]*?(US\$[\d,.]+)", ocr_text)
        
        for name, quantity, unit_price, amount in product_sections:
            result["products"].append({
                "name": name.strip(),
                "quantity": quantity.strip(),
                "unitPrice": unit_price.replace("US$", "").strip(),
                "amount": amount.replace("US$", "").strip()
            })
    
    # 製品情報が抽出できない場合のフォールバック
    if not result["products"]:
        # 基本的な製品名、数量、価格の抽出
        product_names = re.findall(r"Product ([A-Z])", ocr_text)
        quantities = re.findall(r"([\d,]+)\s*kg", ocr_text)
        prices = re.findall(r"US\$([\d,.]+)", ocr_text)
        
        # 抽出できた情報から製品を構成
        for i, name in enumerate(product_names):
            if i < len(quantities) and i*2+1 < len(prices):
                result["products"].append({
                    "name": f"Product {name}",
                    "quantity": quantities[i],
                    "unitPrice": prices[i*2] if i*2 < len(prices) else "",
                    "amount": prices[i*2+1] if i*2+1 < len(prices) else ""
                })

    # 初期化
    quantity = None
    unit_price = None
    amount = None

    # カンマを削除する処理を追加
    if quantity:
        quantity = quantity.replace(',', '')  # 数量のカンマ削除
    if unit_price:
        unit_price = unit_price.replace(',', '')  # 単価のカンマ削除
    if amount:
        amount = amount.replace(',', '')  # 金額のカンマ削除

    # 合計金額の抽出
    result["totalAmount"] = extract_field_by_regex(ocr_text, [
        r"Grand Total.*?US\$\s*([\d,]+)",
        r"Total:?\s*US\$\s*([\d,]+)",
        r"Total Amount:?\s*US\$\s*([\d,]+)"
    ])
    
    # 支払条件の抽出
    result["paymentTerms"] = extract_field_by_regex(ocr_text, [
        r"Payment Terms:\s*(.*?)(?:\n|$)",
        r"Payment:?\s*(.*?)(?:\n|$)"
    ])
    
    # 出荷条件の抽出
    result["terms"] = extract_field_by_regex(ocr_text, [
        r"Incoterms:\s*(.*?)(?:\n|$)",
        r"(?:Shipping|Delivery) Terms:\s*(.*?)(?:\n|$)"
    ])
    
    # 配送先の抽出
    result["destination"] = extract_field_by_regex(ocr_text, [
        r"Discharge Port:\s*(.*?)(?:\n|$)",
        r"(?:Ship to|Destination|Delivery Address):\s*(.*?)(?:\n|$)"
    ])
    
    return result

def extract_format3_data(ocr_text: str) -> Dict[str, Any]:
    """
    フォーマット3（ORDER CONFIMATION）からデータを抽出します
    
    :param ocr_text: OCRで抽出したテキスト
    :return: 構造化されたデータ
    """
    result = {
        "customer": "",
        "poNumber": "",
        "currency": "",
        "products": [],
        "totalAmount": "",
        "paymentTerms": "",
        "terms": "",
        "destination": ""
    }
    
    # 顧客名の抽出
    result["customer"] = extract_field_by_regex(ocr_text, [
        # r"Contract Party\s*:\s*(.*?)(?:\n|$)",
        # r"B/L CONSIGNEE\s*:\s*(.*?)(?:\n|$)"
        r"Contract\s+Party\s*[:\-]?\s*(.*?)(?:\n|$)",
        r"B/L\s+CONSIGNEE\s*[:\-]?\s*(.*?)(?:\n|$)"
    ])
    
    # PO番号の抽出
    result["poNumber"] = extract_field_by_regex(ocr_text, [
        # r"Order No\.\s*(.*?)(?:\n|Grade|Origin)",
        # r"Buyers(?:'|')?\s+Order No\.\s*(.*?)(?:\n|Grade|$)"
        r"Order\s*No\.?\s*[:\-]?\s*([A-Z0-9\-]+)",
        r"Buyers(?:'|’)?\s+Order\s*No\.?\s*[:\-]?\s*([A-Z0-9\-]+)",
        r"Order\s*Number\s*[:\-]?\s*([A-Z0-9\-]+)"
    ])
    
    # 通貨の抽出
    result["currency"] = "USD"  # フォーマット3ではUSDが明示的
    
    # 製品情報の抽出
    grade = extract_field_by_regex(ocr_text, [
        r"Grade\s+([A-Za-z0-9]+)"
    ])
    quantity = extract_field_by_regex(ocr_text, [
        # r"Qt'y\s*\(mt\)\s*([\d.]+)"
        r"Qt['’]?\s*\(mt\.*\)\s*[:\-]?\s*([\d,.]+)",
        r"Quantity\s*[:\-]?\s*([\d,.]+)\s*(?:KG|kg|MT|mt)",
        r"Qty\s*[:\-]?\s*([\d,.]+)"
    ])
    unit_price = extract_field_by_regex(ocr_text, [
        # r"Unit Price\s*\([^)]+\)\s*([\d,.]+)"
        r"Unit\s*Price\s*\([^)]+\)\s*[:\-]?\s*([\d,.]+)",
        r"Unit\s*Price\s*[:\-]?\s*(?:USD|US\$)?\s*([\d,.]+)",
        r"Price\s*[:\-]?\s*(?:USD|US\$)?\s*([\d,.]+)"
    ])
    amount = extract_field_by_regex(ocr_text, [
        # r"Total Amount\s*([\d,.]+)"
        r"Amount\s*[:\-]?\s*USD\s*([\d,.]+)",
        r"Amount\s*[:\-]?\s*([\d,.]+)",
        r"Total\s*Amount\s*[:\-]?\s*([\d,.]+)"
    ])
    
    if grade:
        result["products"].append({
            "name": f"Grade {grade}",
            "quantity": quantity,
            "unitPrice": unit_price,
            "amount": amount
        })

    # カンマを削除する処理を追加
    if quantity:
        quantity = quantity.replace(',', '')  # 数量のカンマ削除
    if unit_price:
        unit_price = unit_price.replace(',', '')  # 単価のカンマ削除
    if amount:
        amount = amount.replace(',', '')  # 金額のカンマ削除

    # 合計金額の抽出
    result["totalAmount"] = extract_field_by_regex(ocr_text, [
        # r"TOTAL.*?USD\s*([\d,.]+)",
        # r"Total Amount\s*USD\s*([\d,.]+)",
        # r"Total Amount\s*([\d,.]+)"
        r"TOTAL\s*USD\s*[:\-]?\s*([\d,.]+)",
        r"Total\s*Amount\s*[:\-]?\s*USD\s*([\d,.]+)",
        r"Total\s*Amount\s*[:\-]?\s*([\d,.]+)",
        r"Grand\s*Total\s*[:\-]?\s*USD\s*([\d,.]+)"
    ])
    
    # 支払条件の抽出
    result["paymentTerms"] = extract_field_by_regex(ocr_text, [
        # r"Payment term\s*\n?\s*(.*?)(?:\n|$)",
        # r"Payment\s*:\s*(.*?)(?:\n|$)"
        r"Payment\s*(?:term|terms?)\s*[:\-]?\s*(.*?)(?:\n|$)",
        r"Terms\s*[:\-]?\s*(.*?)(?:\n|$)",
        r"Payment\s*[:\-]?\s*(.*?)(?:\n|$)"
    ])
    
    # 出荷条件の抽出
    result["terms"] = extract_field_by_regex(ocr_text, [
        # r"Term\s*(.*?)(?:\n|$)",
        # r"CIF\s+(.*?)(?:\n|PORT)"
        r"Term\s*[:\-]?\s*(.*?)(?:\n|$)",
        r"(?:CIF|FOB|EXW)\s+[A-Z\s]+"
    ])
    
    # 配送先の抽出
    result["destination"] = extract_field_by_regex(ocr_text, [
        # r"PORT OF DISCHARGE\s*(.*?)(?:\n|$)",
        # r"PORT OF\s*DISCHARGE\s*(.*?)(?:\n|Payment)"
        r"PORT\s+OF\s+DISCHARGE\s*[:\-]?\s*(.*?)(?:\n|$)",
        r"Discharge\s+Port\s*[:\-]?\s*(.*?)(?:\n|$)",
        r"Destination\s*[:\-]?\s*(.*?)(?:\n|$)"
    ])
    
    return result

def extract_generic_data(ocr_text: str) -> Dict[str, Any]:
    """
    一般的なPOフォーマットからデータを抽出します（フォーマットが特定できない場合）
    
    :param ocr_text: OCRで抽出したテキスト
    :return: 構造化されたデータ
    """
    result = {
        "customer": "",
        "poNumber": "",
        "currency": "",
        "products": [],
        "totalAmount": "",
        "paymentTerms": "",
        "terms": "",
        "destination": ""
    }
    
    # 顧客名を抽出する複数の方法を試す
    customer_patterns = [
        r"(?:Customer|Client|Buyer|Company|Purchaser):\s*(.*?)(?:\n|$)",
        r"(?:To|Bill to):\s*(.*?)(?:\n|$)",
        r"Contract Party\s*:\s*(.*?)(?:\n|$)",
        r"B/L CONSIGNEE\s*:\s*(.*?)(?:\n|$)",
        r"ABC Company\s*(.*?)(?:\n|$)",
        r"\(Buyer(?:'|')s Info\).*?([A-Za-z0-9\s]+Company)"
    ]
    result["customer"] = extract_field_by_regex(ocr_text, customer_patterns)
    
    # PO番号の抽出
    po_patterns = [
        r"(?:PO|Purchase Order|Order) (?:No|Number|#)\.?:?\s*(\w+[-\d]+)",
        r"(?:PO|Purchase Order|Order) (?:No|Number|#)\.?:?\s*(\d+)",
        r"Order No\.\s*(.*?)(?:\n|Grade|Origin)",
        r"Buyers(?:'|')?\s+Order No\.\s*(.*?)(?:\n|Grade|$)"
    ]
    result["poNumber"] = extract_field_by_regex(ocr_text, po_patterns)
    
    # 通貨を抽出
    currency_match = re.search(r"(USD|EUR|JPY|CNY)", ocr_text)
    if currency_match:
        result["currency"] = currency_match.group(1)
    
    # 製品情報の抽出（複数の方法を試す）
    product_extracted = False
    
    # 方法1: 表形式データからの抽出
    product_rows = re.findall(r"([A-Za-z0-9]+)\s+(Product [A-Za-z]|Grade [A-Za-z0-9]+)\s+([\d,]+)\s*(?:kg|mt)\s+(?:US\$)?([\d.]+)\s+(?:US\$)?([\d,.]+)", ocr_text)
    if product_rows:
        for _, name, quantity, unit_price, amount in product_rows:
            result["products"].append({
                "name": name.strip(),
                "quantity": quantity.strip(),
                "unitPrice": unit_price.strip(),
                "amount": amount.strip()
            })
        product_extracted = True
    
    # 方法2: セクション形式からの抽出
    if not product_extracted:
        product_sections = re.findall(r"(?:Product [A-Za-z]|Grade [A-Za-z0-9]+|Item:.*?).*?(\d+)(?:\s*|\n+)(?:kg|mt|KG|MT).*?(?:US\$|Unit Price:?\s*\$?)?\s*([\d,.]+).*?(?:US\$)?\s*([\d,.]+)", ocr_text, re.DOTALL)
        if product_sections:
            for i, (quantity, unit_price, amount) in enumerate(product_sections):
                # 製品名の抽出を試みる
                product_name = ""
                name_match = re.search(r"(?:Product ([A-Z])|Grade ([A-Za-z0-9]+)|Item:\s*(.*?)(?:\n|$))", ocr_text)
                if name_match:
                    if name_match.group(1):
                        product_name = f"Product {name_match.group(1)}"
                    elif name_match.group(2):
                        product_name = f"Grade {name_match.group(2)}"
                    elif name_match.group(3):
                        product_name = name_match.group(3)
                else:
                    product_name = f"Unknown Product {i+1}"
                
                result["products"].append({
                    "name": product_name,
                    "quantity": quantity.strip(),
                    "unitPrice": unit_price.strip(),
                    "amount": amount.strip()
                })
            product_extracted = True
    
    # 方法3: 個別フィールドからの抽出
    if not product_extracted:
        product_name = extract_field_by_regex(ocr_text, [
            r"Item:\s*(.*?)(?:\n|$)",
            r"Product:?\s*(.*?)(?:\n|Quantity)",
            r"Grade\s+([A-Za-z0-9]+)"
        ])
        
        quantity = extract_field_by_regex(ocr_text, [
            r"Quantity:\s*([\d,.]+)\s*(?:KG|kg|MT|mt)",
            r"Qty:?\s*([\d,.]+)\s*(?:KG|kg|MT|mt)",
            r"Qt'y\s*\(mt\)\s*([\d.]+)"
        ])
        
        unit_price = extract_field_by_regex(ocr_text, [
            r"Unit Price:\s*\$?\s*([\d,.]+)",
            r"Unit Price:.*?per\s*.*?\$?\s*([\d,.]+)",
            r"Unit Price\s*\([^)]+\)\s*([\d,.]+)"
        ])
        
        amount = extract_field_by_regex(ocr_text, [
            r"EXT Price:\s*([\d,.]+)",
            r"Amount:\s*([\d,.]+)",
            r"Total Amount\s*([\d,.]+)"
        ])
        
        if product_name or quantity:
            result["products"].append({
                "name": product_name or "Unknown Product",
                "quantity": quantity,
                "unitPrice": unit_price,
                "amount": amount
            })
    
    # 合計金額の抽出
    total_patterns = [
        r"(?:TOTAL|Total|Grand Total).*?(?:USD|US\$)?\s*([\d,.]+)",
        r"Total Amount:?\s*(?:USD|US\$)?\s*([\d,.]+)",
        r"(?:[$]|USD)\s*([\d,.]+)(?:\s+total|\s+USD)"
    ]
    result["totalAmount"] = extract_field_by_regex(ocr_text, total_patterns)
    
    # 支払条件の抽出
    payment_patterns = [
        r"(?:Payment Terms?|Terms of Payment|Terms|Payment):\s*(.*?)(?:\n|$)",
        r"Net Due within\s*(.*?)(?:\n|$)",
        r"Payment term\s*\n?\s*(.*?)(?:\n|$)"
    ]
    result["paymentTerms"] = extract_field_by_regex(ocr_text, payment_patterns)
    
    # 出荷条件の抽出
    terms_patterns = [
        r"(?:Incoterms|Inco Terms|Shipping Terms|Delivery Terms|Term):\s*(.*?)(?:\n|$)",
        r"(?:CIF|FOB|EXW)\s+([A-Za-z\s]+)"
    ]
    result["terms"] = extract_field_by_regex(ocr_text, terms_patterns)
    
    # 配送先の抽出
    destination_patterns = [
        r"(?:Destination|Ship to|Delivery Address|Port of Discharge|Discharge Port|PORT OF DISCHARGE):\s*(.*?)(?:\n|$)",
        r"(?:To|Deliver to):\s*(.*?)(?:\n|$)"
    ]
    result["destination"] = extract_field_by_regex(ocr_text, destination_patterns)
    
    return result