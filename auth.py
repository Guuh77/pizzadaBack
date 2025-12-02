from datetime import datetime, timedelta
from typing import Optional
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import get_settings
from database import execute_query

settings = get_settings()
security = HTTPBearer()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica se a senha está correta"""
    return bcrypt.checkpw(
        plain_password.encode('utf-8'), 
        hashed_password.encode('utf-8')
    )

def get_password_hash(password: str) -> str:
    """Gera hash da senha"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Cria token JWT"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def authenticate_user(email: str, senha: str): # MUDOU para email
    """Autentica usuário"""
    query = """
        SELECT id, nome_completo, senha_hash, setor, is_admin, ativo, data_cadastro, email
        FROM usuarios
        WHERE email = :email AND ativo = 1
    """
    
    result = execute_query(query, {"email": email}, fetch_one=True) # MUDOU para email
    
    if not result:
        return None
    
    user = {
        "id": result[0],
        "nome_completo": result[1],
        "senha_hash": result[2],
        "setor": result[3],
        "is_admin": bool(result[4]),
        "ativo": bool(result[5]),
        "data_cadastro": result[6],
        "email": result[7]
    }
    
    if not verify_password(senha, user["senha_hash"]):
        return None
    
    return user

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Obtém usuário atual do token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais inválidas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    query = """
        SELECT id, nome_completo, setor, is_admin, ativo, data_cadastro
        FROM usuarios
        WHERE id = :user_id AND ativo = 1
    """
    
    result = execute_query(query, {"user_id": user_id}, fetch_one=True)
    
    if not result:
        raise credentials_exception
    
    user = {
        "id": result[0],
        "nome_completo": result[1],
        "setor": result[2],
        "is_admin": bool(result[3]),
        "ativo": bool(result[4]),
        "data_cadastro": result[5]
    }
    
    return user

async def get_current_admin_user(current_user: dict = Depends(get_current_user)):
    """Verifica se usuário é admin"""
    if not current_user["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado. Apenas administradores."
        )
    return current_user