# ocr_service.py
import os
import re
import json
from typing import Dict, Any, Tuple, List
import logging
import pytesseract
from PIL import Image
from pdf2image import convert_from_path
from sqlalchemy.orm import Session

from app import models
from app.ocr_extractors import identify_po_format, extract_format1_data, extract_format2_data, extract_format3_data, extract_generic_data

# ロギング設定
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# OCR処理（Tesseractを使用）
def process_document(file_path: str, ocr_id: int, db: Session):
    """
    ドキュメントを処理してOCRを実行し、結果を保存します。
    
    :param file_path: 処理するファイルのパス
    :param ocr_id: OCR結果のID
    :param db: データベースセッション
    """
    try:
        logger.info(f"OCR処理開始: {file_path}")
        
        # ファイルの拡張子を取得
        _, file_ext = os.path.splitext(file_path)
        file_ext = file_ext.lower()
        
        raw_text = ""
        
        # PDFの場合
        if file_ext == '.pdf':
            try:
                # PDFを画像に変換
                images = convert_from_path(file_path)
                
                # 各ページをOCR処理
                for i, image in enumerate(images):
                    page_text = pytesseract.image_to_string(image, lang='eng+jpn')
                    raw_text += f"\n--- Page {i+1} ---\n{page_text}"
                    logger.debug(f"ページ {i+1} の処理完了")
            except Exception as e:
                logger.error(f"PDF処理エラー: {str(e)}")
                update_ocr_result(db, ocr_id, "", "{}", "failed", f"PDF処理エラー: {str(e)}")
                return
        
        # 画像の場合
        elif file_ext in ['.png', '.jpg', '.jpeg']:
            try:
                image = Image.open(file_path)
                raw_text = pytesseract.image_to_string(image, lang='eng+jpn')
                logger.debug("画像のOCR処理完了")
            except Exception as e:
                logger.error(f"画像処理エラー: {str(e)}")
                update_ocr_result(db, ocr_id, "", "{}", "failed", f"画像処理エラー: {str(e)}")
                return
        
        else:
            # サポートされていないファイル形式
            logger.warning(f"サポートされていないファイル形式: {file_ext}")
            update_ocr_result(db, ocr_id, "", "{}", "failed", "サポートされていないファイル形式です")
            return
        
        # OCR結果を保存
        # 元のファイルパス情報も保存しておく
        processed_data = {
            "file_path": file_path,
            "text_content": raw_text
        }
        # raw_textには長さを整数値として保存し、実際のテキストはprocessed_dataに保存
        update_ocr_result(db, ocr_id, len(raw_text), json.dumps(processed_data), "completed")
        logger.info(f"OCR処理完了: {file_path}")
        
    except Exception as e:
        logger.error(f"OCR処理エラー: {str(e)}")
        update_ocr_result(db, ocr_id, 0, json.dumps({"error": str(e)}), "failed", str(e))

def update_ocr_result(db: Session, ocr_id: int, raw_text_length: int, processed_data: str, status: str, error_message: str = None):
    """
    OCR結果を更新します
    
    :param db: データベースセッション
    :param ocr_id: OCR結果のID
    :param raw_text_length: 抽出されたテキストの長さ（整数値）
    :param processed_data: 処理済みデータ（JSON文字列）
    :param status: 処理状態
    :param error_message: エラーメッセージ（オプション）
    """
    # OCRResultsテーブルのIDカラム名は ocr_id
    ocr_result = db.query(models.OCRResult).filter(models.OCRResult.ocr_id == ocr_id).first()
    
    if ocr_result:
        ocr_result.raw_text = raw_text_length  # 整数値として保存
        ocr_result.processed_data = processed_data
        ocr_result.status = status
        
        if error_message:
            # エラーメッセージがあれば保存
            error_data = json.loads(processed_data) if processed_data and processed_data != "{}" else {}
            error_data["error"] = error_message
            ocr_result.processed_data = json.dumps(error_data)
        
        db.commit()
        logger.info(f"OCR結果更新: ID={ocr_id}, ステータス={status}")
    else:
        logger.warning(f"OCR結果更新失敗: ID={ocr_id} が見つかりません")

def extract_po_data(ocr_data) -> Dict[str, Any]:
    """
    OCRで抽出したテキストから発注書データを抽出します。
    
    :param ocr_data: OCR ID（整数）またはテキスト（文字列）
    :return: 構造化された発注書データ
    """
    # ocr_dataが整数の場合（OCR ID）、テキストを取得
    ocr_text = ""
    if isinstance(ocr_data, int):
        try:
            # DBからOCR結果を取得し、processed_dataからテキストを抽出
            from app.database import SessionLocal
            db = SessionLocal()
            ocr_result = db.query(models.OCRResult).filter(models.OCRResult.ocr_id == ocr_data).first()
            if ocr_result and ocr_result.processed_data:
                try:
                    processed_data = json.loads(ocr_result.processed_data)
                    ocr_text = processed_data.get("text_content", "")
                except json.JSONDecodeError:
                    logger.error(f"JSON解析エラー: {ocr_result.processed_data}")
            db.close()
        except Exception as e:
            logger.error(f"OCRデータ取得エラー: {str(e)}")
    else:
        # 文字列が直接渡された場合
        ocr_text = ocr_data
    
    # フォーマットの判別
    po_format, confidence = identify_po_format(ocr_text)
    logger.info(f"POフォーマット判定: {po_format}, 信頼度: {confidence:.2f}")
    
    # フォーマットに応じたデータ抽出
    if po_format == "format1" and confidence >= 0.4:
        logger.info("Format1 (Buyer's Info) のデータ抽出を実行します")
        result = extract_format1_data(ocr_text)
    elif po_format == "format2" and confidence >= 0.4:
        logger.info("Format2 (Purchase Order) のデータ抽出を実行します")
        result = extract_format2_data(ocr_text)
    elif po_format == "format3" and confidence >= 0.4:
        logger.info("Format3 (ORDER CONFIMATION) のデータ抽出を実行します")
        result = extract_format3_data(ocr_text)
    else:
        logger.info("一般的なフォーマットでのデータ抽出を実行します")
        result = extract_generic_data(ocr_text)
    
    # 結果の検証とクリーニング
    validate_and_clean_result(result)
    
    logger.info(f"PO抽出結果: {result}")
    return result

def validate_and_clean_result(result: Dict[str, Any]):
    """
    抽出結果を検証してクリーニングします。
    
    :param result: 抽出されたデータ
    """
    # 製品情報がない場合の処理
    if not result["products"]:
        logger.warning("製品情報が抽出されませんでした")
        result["products"].append({
            "name": "Unknown Product",
            "quantity": "",
            "unitPrice": "",
            "amount": ""
        })
    
    # 数量が抽出されているが単位が含まれている場合、単位を削除
    for product in result["products"]:
        if product["quantity"] and any(unit in product["quantity"] for unit in ["kg", "KG", "mt", "MT"]):
            product["quantity"] = re.sub(r'[^\d,.]', '', product["quantity"])
        
        # 金額のドル記号などを削除
        if product["unitPrice"] and any(symbol in product["unitPrice"] for symbol in ["$", "USD"]):
            product["unitPrice"] = re.sub(r'[^\d,.]', '', product["unitPrice"])
        
        if product["amount"] and any(symbol in product["amount"] for symbol in ["$", "USD"]):
            product["amount"] = re.sub(r'[^\d,.]', '', product["amount"])
    
    # 合計金額のクリーニング
    if result["totalAmount"] and any(symbol in result["totalAmount"] for symbol in ["$", "USD"]):
        result["totalAmount"] = re.sub(r'[^\d,.]', '', result["totalAmount"])

def analyze_extraction_quality(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    抽出結果の品質を分析します
    
    :param result: 抽出されたデータ
    :return: 品質分析結果
    """
    quality_assessment = {
        "completeness": 0.0,  # 抽出の完全性 (0.0-1.0)
        "confidence": 0.0,    # 抽出の信頼度 (0.0-1.0)
        "missing_fields": [],  # 欠損フィールド
        "recommendation": ""  # 改善推奨事項
    }
    
    # 必須フィールドの定義
    essential_fields = ["customer", "poNumber", "totalAmount"]
    
    # 製品情報の必須サブフィールド
    product_fields = ["name", "quantity", "unitPrice", "amount"]
    
    # 必須フィールドの存在チェック
    missing_fields = [field for field in essential_fields if not result[field]]
    
    # 製品情報のチェック
    has_product = len(result["products"]) > 0
    if has_product:
        first_product = result["products"][0]
        missing_product_fields = [field for field in product_fields if not first_product[field]]
        if missing_product_fields:
            missing_fields.append(f"products({', '.join(missing_product_fields)})")
    else:
        missing_fields.append("products")
    
    # 必須項目の充足率
    total_fields = len(essential_fields) + (len(product_fields) if has_product else 1)
    filled_fields = total_fields - len(missing_fields)
    completeness = filled_fields / total_fields
    
    # 品質評価の設定
    quality_assessment["completeness"] = round(completeness, 2)
    quality_assessment["missing_fields"] = missing_fields
    
    # 信頼度の計算（ここでは単純化して完全性に基づく）
    confidence = min(1.0, completeness * 1.2)  # 完全性よりやや高めに設定（上限1.0）
    quality_assessment["confidence"] = round(confidence, 2)
    
    # 推奨事項
    if completeness < 0.5:
        quality_assessment["recommendation"] = "抽出品質が低いため、手動で入力を確認してください。"
    elif completeness < 0.8:
        quality_assessment["recommendation"] = "不足フィールドを手動で補完することをお勧めします。"
    else:
        quality_assessment["recommendation"] = "抽出品質は良好です。内容を確認して進めてください。"
    
    return quality_assessment

def get_extraction_stats(ocr_text: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """
    OCR抽出の統計情報を取得します
    
    :param ocr_text: OCRで抽出したテキスト
    :param result: 抽出されたデータ
    :return: 統計情報
    """
    stats = {
        "text_length": len(ocr_text),
        "word_count": len(ocr_text.split()),
        "format_candidates": {},
        "extraction_time_ms": 0,  # この値は実際の処理時間測定で更新する必要があります
        "quality_assessment": analyze_extraction_quality(result)
    }
    
    # フォーマット候補のスコアを取得
    format_name, confidence = identify_po_format(ocr_text)
    stats["format_candidates"][format_name] = confidence
    
    # その他の候補フォーマットもスコアリング
    all_formats = ["format1", "format2", "format3", "unknown"]
    for fmt in all_formats:
        if fmt != format_name:
            # ここでは簡易的に信頼度を0.0に設定していますが、
            # 本来は各フォーマットごとに計算すべきです
            stats["format_candidates"][fmt] = 0.0
    
    return stats

def process_ocr_with_enhanced_extraction(file_path: str, ocr_id: int, db: Session):
    """
    拡張抽出機能を持つOCR処理を実行します
    
    :param file_path: 処理するファイルのパス
    :param ocr_id: OCR結果のID
    :param db: データベースセッション
    """
    try:
        logger.info(f"拡張OCR処理開始: {file_path}")
        
        # 基本的なOCR処理を実行
        process_document(file_path, ocr_id, db)
        
        # OCR結果を取得
        ocr_result = db.query(models.OCRResult).filter(models.OCRResult.ocr_id == ocr_id).first()
        if not ocr_result or ocr_result.status != "completed":
            logger.warning(f"OCR処理が完了していません: ID={ocr_id}")
            return
        
        # processed_dataからテキスト内容を取得
        processed_data = json.loads(ocr_result.processed_data)
        ocr_text = processed_data.get("text_content", "")
        
        # PO情報の抽出
        extracted_data = extract_po_data(ocr_text)
        
        # 抽出統計情報の取得
        stats = get_extraction_stats(ocr_text, extracted_data)
        
        # 抽出結果と統計情報を含む完全な結果を保存
        complete_result = {
            "data": extracted_data,
            "stats": stats,
            "file_path": file_path,
            "text_content": ocr_text  # テキスト内容を保持
        }
        
        # 結果の保存
        ocr_result.processed_data = json.dumps(complete_result)
        db.commit()
        
        logger.info(f"拡張OCR処理完了: ID={ocr_id}, フォーマット={stats['format_candidates']}")
        
    except Exception as e:
        logger.error(f"拡張OCR処理エラー: {str(e)}")
        try:
            ocr_result = db.query(models.OCRResult).filter(models.OCRResult.ocr_id == ocr_id).first()
            if ocr_result:
                ocr_result.status = "failed"
                processed_data = json.loads(ocr_result.processed_data) if ocr_result.processed_data and ocr_result.processed_data != "{}" else {}
                processed_data["error"] = str(e)
                ocr_result.processed_data = json.dumps(processed_data)
                db.commit()
        except Exception as inner_e:
            logger.error(f"エラー情報保存中にエラー発生: {str(inner_e)}")
