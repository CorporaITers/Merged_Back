# ocr_service.py - Azure App Service対応修正版（現行ベース）
import os
import re
import json
import tempfile
import uuid
from typing import Dict, Any, Tuple, List, Optional
import logging
from datetime import datetime
from pathlib import Path

import pytesseract
from PIL import Image
from pdf2image import convert_from_path
from sqlalchemy.orm import Session

from app import models
from app.database import SessionLocal  # 既存のdatabase.pyを使用
from app.config import OCR_TEMP_FOLDER, TESSERACT_CMD, MAX_FILE_SIZE  # 現行config.pyを使用
from app.ocr_extractors import (
    identify_po_format, 
    extract_format1_data, 
    extract_format2_data, 
    extract_format3_data, 
    extract_generic_data
)

# ロギング設定
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ========== Azure対応の新機能追加 ==========

def setup_tesseract_for_azure():
    """Azure環境でのTesseract設定（新規追加）"""
    try:
        # Azure環境判定
        is_azure = os.getenv("WEBSITE_SITE_NAME") is not None
        
        if is_azure:
            logger.info("🔧 Azure環境でのTesseract設定を実行中...")
            
            # 複数のパスを試行
            tesseract_paths = [
                "/usr/bin/tesseract",
                "/usr/local/bin/tesseract", 
                "/opt/conda/bin/tesseract",
                "tesseract"  # PATH内検索
            ]
            
            for path in tesseract_paths:
                try:
                    pytesseract.pytesseract.tesseract_cmd = path
                    # テスト実行
                    version = pytesseract.get_tesseract_version()
                    logger.info(f"✅ Tesseract設定成功: {path} (version: {version})")
                    return True
                except Exception as e:
                    logger.debug(f"❌ Tesseractパス失敗: {path} - {e}")
                    continue
            
            # 全て失敗した場合の警告
            logger.warning("⚠️ Tesseractバイナリが見つかりませんでした。フォールバック処理を使用します。")
            return False
        else:
            # ローカル環境での通常設定
            if TESSERACT_CMD and os.path.exists(TESSERACT_CMD):
                pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
                logger.info(f"✅ Tesseract設定完了: {TESSERACT_CMD}")
                return True
    
    except ImportError:
        logger.error("❌ pytesseractのインポートに失敗しました")
        return False
    except Exception as e:
        logger.error(f"❌ Tesseract設定エラー: {e}")
        return False

def process_document_fallback(file_path: str, ocr_id: int, db: Session):
    """Tesseractが利用できない場合のフォールバック処理（新規追加）"""
    try:
        logger.info("🔄 フォールバック処理: 基本的なPDF解析を実行中...")
        
        # PDFMinerを使用したテキスト抽出
        raw_text = ""
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext == '.pdf':
            try:
                from pdfminer.high_level import extract_text
                raw_text = extract_text(file_path)
                logger.info("✅ PDFMinerによるテキスト抽出完了")
            except Exception as e:
                logger.error(f"❌ PDFMiner処理エラー: {e}")
                raw_text = f"PDF処理エラー: {str(e)}\n\nOCR機能を利用するにはTesseractが必要です。"
        
        elif file_ext in ['.png', '.jpg', '.jpeg']:
            # 画像ファイルの場合はエラーメッセージ
            raw_text = "画像ファイルのOCR処理にはTesseractが必要です。現在の環境では利用できません。"
        
        else:
            raw_text = f"サポートされていないファイル形式: {file_ext}"
        
        # 結果を保存
        processed_data = {
            "original_filename": os.path.basename(file_path),
            "text_content": raw_text,
            "processing_method": "fallback_pdfminer",
            "processing_timestamp": datetime.utcnow().isoformat(),
            "warning": "Tesseractが利用できないため、制限された処理を実行しました。"
        }
        
        update_ocr_result(db, ocr_id, raw_text, json.dumps(processed_data), "completed")
        logger.info("✅ フォールバック処理完了")
        
    except Exception as e:
        logger.error(f"❌ フォールバック処理エラー: {e}")
        update_ocr_result(db, ocr_id, "", json.dumps({"error": str(e)}), "failed", str(e))

# 一時ファイル管理クラス（Azure対応修正版）
class TempFileManager:
    def __init__(self):
        # Azure環境対応の一時ディレクトリ選択
        is_azure = os.getenv("WEBSITE_SITE_NAME") is not None
        
        if is_azure:
            # Azure環境では複数の候補から書き込み可能なディレクトリを選択
            temp_candidates = [
                OCR_TEMP_FOLDER,
                "/tmp/po_uploads", 
                "/home/site/wwwroot/temp",
                tempfile.gettempdir(),
                "/tmp"
            ]
            
            self.temp_dir = None
            for candidate in temp_candidates:
                try:
                    candidate_path = Path(candidate)
                    candidate_path.mkdir(parents=True, exist_ok=True)
                    
                    # 書き込みテスト
                    test_file = candidate_path / "write_test.tmp"
                    test_file.write_text("test")
                    test_file.unlink()
                    
                    self.temp_dir = candidate_path
                    logger.info(f"✅ 一時ディレクトリ設定完了: {self.temp_dir}")
                    break
                    
                except (OSError, PermissionError) as e:
                    logger.debug(f"❌ 一時ディレクトリ候補失敗: {candidate} - {e}")
                    continue
            
            if not self.temp_dir:
                # 最後の手段
                self.temp_dir = Path(tempfile.gettempdir())
                logger.warning(f"⚠️ 一時ディレクトリをシステムデフォルトに設定: {self.temp_dir}")
        else:
            # ローカル環境（現行の処理）
            self.temp_dir = Path(OCR_TEMP_FOLDER)
            self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    def save_uploaded_file(self, file_data: bytes, filename: str) -> str:
        """アップロードファイルを一時保存（Azure対応）"""
        # セキュアなファイル名生成
        safe_filename = f"{uuid.uuid4()}_{filename}"
        if not self.temp_dir:
            raise ValueError("Temporary directory is not initialized.")
        file_path = self.temp_dir / safe_filename
        
        try:
            with open(file_path, 'wb') as f:
                f.write(file_data)
            logger.debug(f"📁 一時ファイル保存完了: {file_path}")
            return str(file_path)
        except Exception as e:
            logger.error(f"❌ 一時ファイル保存エラー: {e}")
            raise
    
    def cleanup_file(self, file_path: str):
        """処理完了後のファイル削除（Azure対応）"""
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
                logger.debug(f"🧹 一時ファイル削除完了: {file_path}")
        except OSError as e:
            logger.warning(f"⚠️ ファイル削除失敗: {file_path} - {e}")

# OCR処理（Azure対応修正版）
def process_document(file_path: str, ocr_id: int, db: Session):
    """
    ドキュメントを処理してOCRを実行し、結果を保存します。
    Azure App Service対応版
    
    :param file_path: 処理するファイルのパス
    :param ocr_id: OCR結果のID
    :param db: データベースセッション
    """
    try:
        logger.info(f"OCR処理開始: {file_path}")
        
        # Tesseractの設定確認（Azure対応）
        tesseract_available = setup_tesseract_for_azure()
        
        if not tesseract_available:
            # Tesseractが利用できない場合はフォールバック処理
            logger.warning("⚠️ Tesseractが利用できません。フォールバック処理を実行します。")
            return process_document_fallback(file_path, ocr_id, db)
        
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
                # PDFエラーの場合もフォールバック処理を試行
                logger.info("PDF→OCR処理に失敗したため、フォールバック処理を実行します。")
                return process_document_fallback(file_path, ocr_id, db)
        
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
        
        # OCR結果を保存（ファイルパスは保存しない）
        processed_data = {
            "original_filename": os.path.basename(file_path),
            "text_content": raw_text,
            "processing_method": "tesseract_ocr",
            "processing_timestamp": datetime.utcnow().isoformat()
        }
        
        # raw_textとしてテキスト内容を保存、processed_dataに詳細を保存
        update_ocr_result(db, ocr_id, raw_text, json.dumps(processed_data), "completed")
        logger.info(f"OCR処理完了: {file_path}")
        
    except Exception as e:
        logger.error(f"OCR処理エラー: {str(e)}")
        # 最終的なエラーの場合もフォールバック処理を試行
        try:
            logger.info("OCR処理エラーのため、最終フォールバック処理を実行します。")
            process_document_fallback(file_path, ocr_id, db)
        except Exception as fallback_error:
            logger.error(f"フォールバック処理も失敗: {fallback_error}")
            update_ocr_result(db, ocr_id, "", json.dumps({"error": str(e)}), "failed", str(e))

# 既存の関数（修正なし、型注釈の改善のみ）
def update_ocr_result(db: Session, ocr_id: int, raw_text: str, processed_data: str, status: str, error_message: Optional[str] = None):
    """
    OCR結果を更新します（models.pyのOCRResultテーブル対応）
    
    :param db: データベースセッション
    :param ocr_id: OCR結果のID
    :param raw_text: 抽出されたテキスト（Text型に対応）
    :param processed_data: 処理済みデータ（JSON文字列）
    :param status: 処理状態
    :param error_message: エラーメッセージ（オプション）
    """
    try:
        ocr_result = db.query(models.OCRResult).filter(models.OCRResult.ocr_id == ocr_id).first()
        
        if ocr_result:
            ocr_result.raw_text = raw_text  # type: ignore # Text型なので文字列を保存
            ocr_result.processed_data = processed_data # type: ignore
            ocr_result.status = status # type: ignore
            
            if error_message:
                # エラーメッセージがあれば保存
                try:
                    error_data = json.loads(processed_data) if processed_data and processed_data != "{}" else {}
                except json.JSONDecodeError:
                    error_data = {}
                error_data["error"] = error_message
                ocr_result.processed_data = json.dumps(error_data) # type: ignore
            
            db.commit()
            logger.info(f"OCR結果更新: ID={ocr_id}, ステータス={status}")
        else:
            logger.warning(f"OCR結果更新失敗: ID={ocr_id} が見つかりません")
    except Exception as e:
        logger.error(f"OCR結果更新エラー: {str(e)}")
        db.rollback()

def process_document_from_bytes(file_data: bytes, filename: str, ocr_id: int, db: Session):
    """
    ファイルデータから直接OCR処理を実行（Azure対応）
    
    :param file_data: ファイルのバイトデータ
    :param filename: ファイル名
    :param ocr_id: OCR結果のID
    :param db: データベースセッション
    """
    temp_manager = TempFileManager()
    temp_path = None
    
    try:
        # 1. 一時ファイルとして保存
        temp_path = temp_manager.save_uploaded_file(file_data, filename)
        logger.info(f"一時ファイル作成: {temp_path}")
        
        # 2. 既存のOCR処理を実行
        process_document(temp_path, ocr_id, db)
        
    except Exception as e:
        logger.error(f"バイトデータからのOCR処理エラー: {str(e)}")
        update_ocr_result(db, ocr_id, "", json.dumps({"error": str(e)}), "failed", str(e))
    
    finally:
        # 3. 一時ファイル削除
        if temp_path:
            temp_manager.cleanup_file(temp_path)

# 既存の関数（修正なし）
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
            # DBからOCR結果を取得し、raw_textからテキストを抽出
            db = SessionLocal()
            ocr_result = db.query(models.OCRResult).filter(models.OCRResult.ocr_id == ocr_data).first()
            if ocr_result and ocr_result.raw_text is not None:
                ocr_text = str(ocr_result.raw_text)
            else:
                # processed_dataからも試す
                if ocr_result and ocr_result.processed_data: # type: ignore
                    try:
                        processed_data = json.loads(str(ocr_result.processed_data))
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
    """抽出結果の品質を分析します"""
    quality_assessment = {
        "completeness": 0.0,
        "confidence": 0.0,
        "missing_fields": [],
        "recommendation": ""
    }
    
    essential_fields = ["customer", "poNumber", "totalAmount"]
    product_fields = ["name", "quantity", "unitPrice", "amount"]
    
    missing_fields = [field for field in essential_fields if not result[field]]
    
    has_product = len(result["products"]) > 0
    if has_product:
        first_product = result["products"][0]
        missing_product_fields = [field for field in product_fields if not first_product[field]]
        if missing_product_fields:
            missing_fields.append(f"products({', '.join(missing_product_fields)})")
    else:
        missing_fields.append("products")
    
    total_fields = len(essential_fields) + (len(product_fields) if has_product else 1)
    filled_fields = total_fields - len(missing_fields)
    completeness = filled_fields / total_fields
    
    quality_assessment["completeness"] = round(completeness, 2)
    quality_assessment["missing_fields"] = missing_fields
    
    confidence = min(1.0, completeness * 1.2)
    quality_assessment["confidence"] = round(confidence, 2)
    
    if completeness < 0.5:
        quality_assessment["recommendation"] = "抽出品質が低いため、手動で入力を確認してください。"
    elif completeness < 0.8:
        quality_assessment["recommendation"] = "不足フィールドを手動で補完することをお勧めします。"
    else:
        quality_assessment["recommendation"] = "抽出品質は良好です。内容を確認して進めてください。"
    
    return quality_assessment

def get_extraction_stats(ocr_text: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """OCR抽出の統計情報を取得します"""
    stats = {
        "text_length": len(ocr_text),
        "word_count": len(ocr_text.split()),
        "format_candidates": {},
        "extraction_time_ms": 0,
        "quality_assessment": analyze_extraction_quality(result)
    }
    
    format_name, confidence = identify_po_format(ocr_text)
    stats["format_candidates"][format_name] = confidence
    
    all_formats = ["format1", "format2", "format3", "unknown"]
    for fmt in all_formats:
        if fmt != format_name:
            stats["format_candidates"][fmt] = 0.0
    
    return stats

def process_ocr_with_enhanced_extraction(file_data: bytes, filename: str, ocr_id: int):
    """
    拡張抽出機能を持つOCR処理を実行します（Azure対応版）
    ※ 新しいDBセッションを内部で作成
    
    :param file_data: ファイルのバイトデータ
    :param filename: ファイル名
    :param ocr_id: OCR結果のID
    """
    # 新しいDBセッションを作成
    db = SessionLocal()
    
    try:
        logger.info(f"拡張OCR処理開始: {filename}")
        
        # ファイルデータから処理
        process_document_from_bytes(file_data, filename, ocr_id, db)
        
        # OCR結果を取得
        ocr_result = db.query(models.OCRResult).filter(models.OCRResult.ocr_id == ocr_id).first()
        if not ocr_result or ocr_result.status != "completed":  # type: ignore
            logger.warning(f"OCR処理が完了していません: ID={ocr_id}")
            return
        
        # raw_textまたはprocessed_dataからテキスト内容を取得
        ocr_text = ""
        if ocr_result.raw_text is not None:
            ocr_text = str(ocr_result.raw_text)
        elif ocr_result.processed_data is not None:
            try:
                processed_data = json.loads(str(ocr_result.processed_data))
                ocr_text = processed_data.get("text_content", "")
            except json.JSONDecodeError:
                logger.error(f"JSON解析エラー: {ocr_result.processed_data}")
        
        # PO情報の抽出
        extracted_data = extract_po_data(ocr_text)
        
        # 抽出統計情報の取得
        stats = get_extraction_stats(ocr_text, extracted_data)
        
        # 抽出結果と統計情報を含む完全な結果を保存
        complete_result = {
            "data": extracted_data,
            "stats": stats,
            "original_filename": filename,
            "text_content": ocr_text
        }
        
        # 結果の保存
        ocr_result.processed_data = json.dumps(complete_result) # type: ignore
        db.commit()
        
        logger.info(f"拡張OCR処理完了: ID={ocr_id}")
        
    except Exception as e:
        logger.error(f"拡張OCR処理エラー: {str(e)}")
        try:
            ocr_result = db.query(models.OCRResult).filter(models.OCRResult.ocr_id == ocr_id).first()
            if ocr_result:
                ocr_result.status = "failed" # type: ignore
                error_data = {"error": str(e)}
                ocr_result.processed_data = json.dumps(error_data)  # type: ignore
                db.commit()
        except Exception as inner_e:
            logger.error(f"エラー情報保存中にエラー発生: {str(inner_e)}")
    
    finally:
        db.close()