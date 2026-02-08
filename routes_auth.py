from fastapi import APIRouter, HTTPException, status, Depends
from datetime import timedelta, datetime
import secrets 
import string 
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from models import (
    UsuarioCreate, UsuarioLogin, Token, UsuarioResponse,
    MessageResponse, ForgotPasswordRequest, ResetPasswordRequest
)
from auth import (
    get_password_hash, 
    authenticate_user, 
    create_access_token,
    get_current_user
)
from database import execute_query, get_db_connection
from config import get_settings

router = APIRouter(prefix="/auth", tags=["Autenticação"])
settings = get_settings()

def generate_numeric_code(length: int = 6) -> str:
    """Gera um código numérico de X dígitos"""
    return "".join(secrets.choice(string.digits) for _ in range(length))

def send_reset_code_email(to_email: str, code: str):
    """
    Envia e-mail de redefinição de senha via Gmail SMTP
    """
    settings = get_settings()
    
    # Configurações do Gmail SMTP
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    sender_email = settings.SMTP_EMAIL
    sender_password = settings.SMTP_PASSWORD

    # Criar mensagem
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "[PIZZADA DO LELO] Seu Código de Redefinição de Senha"
    msg["From"] = f"Pizzada do Lelo <{sender_email}>"
    msg["To"] = to_email

    # Conteúdo HTML
    html_content = f"""
        <div style="font-family: Arial, sans-serif; line-height: 1.6;">
            <h2>Olá!</h2>
            <p>Recebemos uma solicitação para redefinir sua senha no sistema PIZZADA DO LELO.</p>
            <p>Use o código abaixo para criar uma nova senha:</p>
            <h1 style="font-size: 36px; letter-spacing: 4px; color: #E63946;">
                {code}
            </h1>
            <p>Este código expira em 15 minutos.</p>
            <p>Se você não solicitou isso, pode ignorar este e-mail.</p>
            <br>
            <p>Atenciosamente,</p>
            <p>Equipe PIZZADA DO LELO 🍕</p>
        </div>
    """
    
    part = MIMEText(html_content, "html")
    msg.attach(part)

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, msg.as_string())
        print(f"E-mail enviado para {to_email}")
    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Não foi possível enviar o e-mail de redefinição. Erro: {str(e)}"
        )

@router.post("/register", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
async def register(user: UsuarioCreate):
    check_query = "SELECT id FROM usuarios WHERE email = :email"
    existing = execute_query(check_query, {"email": user.email}, fetch_one=True)
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário já existe com este e-mail"
        )
    
    hashed_password = get_password_hash(user.senha)
    
    insert_query = """
        INSERT INTO usuarios (nome_completo, email, senha_hash, setor, is_admin)
        VALUES (:nome, :email, :senha, :setor, :admin)
    """
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            insert_query,
            {
                "nome": user.nome_completo,
                "email": user.email,
                "senha": hashed_password,
                "setor": user.setor,
                "admin": 1 if user.is_admin else 0
            }
        )
        conn.commit()
        
        select_query = """
            SELECT id, nome_completo, email, setor, is_admin, ativo, data_cadastro
            FROM usuarios
            WHERE email = :email
        """
        cursor.execute(select_query, {"email": user.email})
        result = cursor.fetchone()
        cursor.close()
    
    return UsuarioResponse(
        id=result[0],
        nome_completo=result[1],
        email=result[2],
        setor=result[3],
        is_admin=bool(result[4]),
        ativo=bool(result[5]),
        data_cadastro=result[6]
    )

@router.post("/login", response_model=Token)
async def login(credentials: UsuarioLogin):
    user = authenticate_user(credentials.email, credentials.senha)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user["id"])}, expires_delta=access_token_expires
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UsuarioResponse(
            id=user["id"],
            nome_completo=user["nome_completo"],
            email=user["email"],
            setor=user["setor"],
            is_admin=user["is_admin"],
            ativo=user["ativo"],
            data_cadastro=user["data_cadastro"]
        )
    )

@router.get("/me", response_model=UsuarioResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    if "email" not in current_user:
        query = "SELECT email FROM usuarios WHERE id = :id"
        result = execute_query(query, {"id": current_user["id"]}, fetch_one=True)
        current_user["email"] = result[0] if result else ""

    return UsuarioResponse(
        id=current_user["id"],
        nome_completo=current_user["nome_completo"],
        email=current_user["email"],
        setor=current_user["setor"],
        is_admin=current_user["is_admin"],
        ativo=current_user["ativo"],
        data_cadastro=current_user["data_cadastro"]
    )


@router.put("/me", response_model=UsuarioResponse)
async def update_me(
    data: dict,
    current_user: dict = Depends(get_current_user)
):
    """Atualiza dados do usuário logado (apenas nome por enquanto)"""
    nome_completo = data.get("nome_completo")
    
    if not nome_completo or len(nome_completo.strip()) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome deve ter pelo menos 3 caracteres"
        )
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE usuarios SET nome_completo = :nome WHERE id = :id",
            {"nome": nome_completo.strip(), "id": current_user["id"]}
        )
        conn.commit()
        
        cursor.execute("""
            SELECT id, nome_completo, email, setor, is_admin, ativo, data_cadastro
            FROM usuarios WHERE id = :id
        """, {"id": current_user["id"]})
        row = cursor.fetchone()
        cursor.close()
    
    return UsuarioResponse(
        id=row[0],
        nome_completo=row[1],
        email=row[2],
        setor=row[3],
        is_admin=bool(row[4]),
        ativo=bool(row[5]),
        data_cadastro=row[6]
    )

@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(request: ForgotPasswordRequest):
    query = "SELECT id FROM usuarios WHERE email = :email AND ativo = 1"
    user = execute_query(query, {"email": request.email}, fetch_one=True)
    
    if not user:
        return MessageResponse(
            message="Se um usuário com esse e-mail existir, um código de redefinição será enviado."
        )
    
    user_id = user[0]
    codigo = generate_numeric_code(6)
    data_expiracao = datetime.utcnow() + timedelta(minutes=15)
    
    insert_query = """
        INSERT INTO codigos_reset_senha (usuario_id, codigo, data_expiracao)
        VALUES (:usuario_id, :codigo, :data_expiracao)
    """
    
    execute_query(
        insert_query,
        {"usuario_id": user_id, "codigo": codigo, "data_expiracao": data_expiracao},
        commit=True
    )

    send_reset_code_email(to_email=request.email, code=codigo)
    
    return MessageResponse(
        message=f"Um código de 6 dígitos foi enviado para o e-mail {request.email}."
    )

@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(request: ResetPasswordRequest):
    select_query = """
        SELECT c.id, c.usuario_id, c.data_expiracao, c.usado
        FROM codigos_reset_senha c
        JOIN usuarios u ON c.usuario_id = u.id
        WHERE u.email = :email AND c.codigo = :codigo
        ORDER BY c.data_criacao DESC
        FETCH FIRST 1 ROWS ONLY
    """
    
    codigo_data = execute_query(
        select_query,
        {"email": request.email, "codigo": request.codigo},
        fetch_one=True
    )
    
    if not codigo_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código ou e-mail inválido"
        )
    
    codigo_id = codigo_data[0]
    usuario_id = codigo_data[1]
    data_expiracao = codigo_data[2]
    usado = codigo_data[3]
    
    if usado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código já foi utilizado"
        )
    
    if datetime.utcnow() > data_expiracao:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código expirou"
        )
    
    nova_senha_hash = get_password_hash(request.nova_senha)
    
    update_user_query = "UPDATE usuarios SET senha_hash = :senha_hash WHERE id = :usuario_id"
    update_codigo_query = "UPDATE codigos_reset_senha SET usado = 1 WHERE id = :codigo_id"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(update_user_query, {"senha_hash": nova_senha_hash, "usuario_id": usuario_id})
        cursor.execute(update_codigo_query, {"codigo_id": codigo_id})
        conn.commit()
        cursor.close()
    
    return MessageResponse(message="Senha atualizada com sucesso!")

@router.get("/usuarios", response_model=list[UsuarioResponse])
async def listar_usuarios(
    current_user: dict = Depends(get_current_user)
):
    """Lista todos os usuários ativos (para seleção em eventos RELAMPAGO)"""
    
    # Apenas admins podem listar usuários
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem visualizar a lista de usuários"
        )
    
    query = """
        SELECT id, nome_completo, email, setor, is_admin, ativo, data_cadastro
        FROM usuarios
        WHERE ativo = 1
        ORDER BY nome_completo
    """
    
    results = execute_query(query)
    
    return [
        UsuarioResponse(
            id=row["ID"],
            nome_completo=row["NOME_COMPLETO"],
            email=row.get("EMAIL", ""),
            setor=row["SETOR"],
            is_admin=bool(row["IS_ADMIN"]),
            ativo=bool(row["ATIVO"]),
            data_cadastro=row.get("DATA_CADASTRO")
        )
        for row in results
    ]