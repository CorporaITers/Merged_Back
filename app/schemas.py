# schemas.py
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime


# ユーザー関連
class UserBase(BaseModel):
    email: EmailStr
    name: str

class UserCreate(UserBase):
    password: str
    role: Optional[str] = "user"

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class User(UserBase):
    id: int
    role: str
    created_at: datetime

    model_config = {
        "from_attributes": True
    }

# トークン
class Token(BaseModel):
    token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

# 製品情報
class ProductItem(BaseModel):
    name: str
    quantity: str
    unitPrice: str
    amount: str

# PO作成
class POCreate(BaseModel):
    customer: str
    poNumber: str
    currency: str
    products: List[ProductItem]
    totalAmount: str
    paymentTerms: str
    terms: str
    destination: str

# ステータス更新
class StatusUpdate(BaseModel):
    status: str  # '手配前', '手配中', '手配済', '計上済' のいずれか

# OCRレスポンス
class OCRResponse(BaseModel):
    ocrId: str
    status: str

# OCR抽出データレスポンス
class OCRExtractResponse(BaseModel):
    ocrId: int
    data: dict

# POレジスターレスポンス
class PORegisterResponse(BaseModel):
    success: bool
    poId: int

# POアイテム（一覧用）
class POListItem(BaseModel):
    id: int
    status: str
    acquisitionDate: Optional[str] = None
    organization: Optional[str] = None
    invoice: str
    payment: str
    booking: str
    manager: str
    invoiceNumber: Optional[str] = None
    poNumber: str
    customer: str
    productName: str
    quantity: float
    currency: Optional[str] = None
    unitPrice: Optional[str] = None
    amount: Optional[str] = None
    paymentTerms: Optional[str] = None
    terms: Optional[str] = None
    destination: Optional[str] = None
    transitPoint: Optional[str] = None
    cutOffDate: Optional[str] = None
    etd: Optional[str] = None
    eta: Optional[str] = None
    bookingNumber: Optional[str] = None
    vesselName: Optional[str] = None
    voyageNumber: Optional[str] = None
    containerInfo: Optional[str] = None
    memo: Optional[str] = None

# PO一覧レスポンス
class POListResponse(BaseModel):
    success: bool
    data: List[POListItem]