# auth.py
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import logging

from app.database import get_db
from app import models
from app import config

# ロギング設定
logger = logging.getLogger(__name__)

# パスワードハッシュ化
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# トークン認証の設定
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

# パスワードのハッシュ化
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

# パスワードの検証
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

# JWTトークン生成
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.ALGORITHM)
    return encoded_jwt

# 開発環境用のユーザー取得
def get_dev_user(db: Session):
    # データベースから最初のユーザーを取得
    dev_user = db.query(models.User).first()
    
    # ユーザーが存在しない場合は新規作成
    if not dev_user:
        logger.info("開発モード: ユーザーが見つからないため新規作成します")
        dev_user = models.User(
            name="開発ユーザー",
            email="dev@example.com",
            password_hash=get_password_hash("devpass"),
            role="admin"
        )
        db.add(dev_user)
        db.commit()
        db.refresh(dev_user)
    
    return dev_user

# 現在のユーザーを取得
async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    # 開発環境モードの場合は認証をバイパス
    if config.DEV_MODE:
        logger.debug("開発モード: 認証をバイパスします")
        return get_dev_user(db)
    
    # 本番環境の通常の認証ロジック
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="認証情報が無効です",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        logger.debug(f"トークンの検証を開始: {token[:10]}...")
        
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        email = payload.get("sub")
        if not isinstance(email, str):
            logger.warning("ペイロードに有効なemailが含まれていません")
            raise credentials_exception
        
        logger.debug(f"デコードされたペイロード: {payload}")
        
        if email is None:
            logger.warning("ペイロードにemailが含まれていません")
            raise credentials_exception
    except JWTError as e:
        logger.error(f"JWT検証エラー: {e}")
        raise credentials_exception
    
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        logger.warning(f"指定されたメールアドレスのユーザーが見つかりません: {email}")
        raise credentials_exception
    
    return user