from fastapi import APIRouter, HTTPException, status, Depends, Request
from datetime import timedelta, datetime, timezone
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
    get_current_user,
    get_current_admin_user
)
from database import execute_query, get_db_connection
from config import get_settings

router = APIRouter(prefix="/auth", tags=["Autenticação"])
settings = get_settings()

# Rate limiter (importa instância do main)
from slowapi import Limiter
from slowapi.util import get_remote_address
limiter = Limiter(key_func=get_remote_address)

def compute_is_premium(user_id: int) -> bool:
    """Computa status premium: 5+ pizzadas E 10+ sabores diferentes. Nunca salvo no DB."""

    query = """
        SELECT
            COUNT(DISTINCT p.evento_id) as total_pizzadas,
            COUNT(DISTINCT ip.sabor_id) as sabores_diferentes
        FROM pedidos p
        LEFT JOIN itens_pedido ip ON ip.pedido_id = p.id
        WHERE p.usuario_id = :user_id
    """
    result = execute_query(query, {"user_id": user_id}, fetch_one=True)
    if not result:
        return False
    total_pizzadas = result["TOTAL_PIZZADAS"] or 0
    sabores_diferentes = result["SABORES_DIFERENTES"] or 0
    return total_pizzadas >= 5 and sabores_diferentes >= 10

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
        print(f"[SMTP ERROR] Erro ao enviar e-mail: {e}")  # Logar internamente
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível enviar o e-mail de redefinição. Tente novamente mais tarde."
        )

@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(request: Request, user: UsuarioCreate):
    check_query = "SELECT id FROM usuarios WHERE email = :email"
    existing = execute_query(check_query, {"email": user.email}, fetch_one=True)
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário já existe com este e-mail"
        )
    
    hashed_password = get_password_hash(user.senha)
    
    insert_query = """
        INSERT INTO usuarios (nome_completo, email, senha_hash, setor, is_admin, ativo)
        VALUES (:nome, :email, :senha, :setor, :admin, :ativo)
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
                "admin": 0,
                "ativo": 0  # Pendente - aguardando aprovação do admin
            }
        )
        conn.commit()
        cursor.close()
    
    return {"message": "Cadastro enviado com sucesso! Aguarde a aprovação de um administrador.", "pendente": True}

@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
async def login(request: Request, credentials: UsuarioLogin):
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
    
    # [Fase 3] Auditoria de login seguro
    try:
        ip_addr = request.client.host if request.client else "unknown"
        query = """
            INSERT INTO auditoria_logs (usuario_id, acao, detalhes, ip_address)
            VALUES (:user_id, 'LOGIN', 'Login realizado no sistema', :ip)
        """
        execute_query(query, {"user_id": user["id"], "ip": ip_addr}, commit=True)
    except Exception as e:
        print(f"Erro ao auditar login: {e}")
        pass  # Ignora falhas para não impedir o login
    
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
            is_premium=compute_is_premium(user["id"]),
            data_cadastro=user["data_cadastro"]
        )
    )

@router.get("/me", response_model=UsuarioResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    if "email" not in current_user:
        query = "SELECT email FROM usuarios WHERE id = :id"
        result = execute_query(query, {"id": current_user["id"]}, fetch_one=True)
        current_user["email"] = result["EMAIL"] if result else ""

    return UsuarioResponse(
        id=current_user["id"],
        nome_completo=current_user["nome_completo"],
        email=current_user["email"],
        setor=current_user["setor"],
        is_admin=current_user["is_admin"],
        ativo=current_user["ativo"],
        is_premium=compute_is_premium(current_user["id"]),
        data_cadastro=current_user["data_cadastro"]
    )


from pydantic import BaseModel as _BaseModel, Field as _Field

class UsuarioUpdateMe(_BaseModel):
    nome_completo: str = _Field(..., min_length=3, max_length=200)

@router.put("/me", response_model=UsuarioResponse)
async def update_me(
    data: UsuarioUpdateMe,
    current_user: dict = Depends(get_current_user)
):
    """Atualiza dados do usuário logado (apenas nome por enquanto)"""
    nome_completo = data.nome_completo
    
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
        is_premium=compute_is_premium(row[0]),
        data_cadastro=row[6]
    )

@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit("3/minute")
async def forgot_password(request: Request, body: ForgotPasswordRequest):
    MENSAGEM_PADRAO = "Se um usuário com esse e-mail existir, um código de redefinição será enviado."
    
    query = "SELECT id FROM usuarios WHERE email = :email AND ativo = 1"
    user = execute_query(query, {"email": body.email}, fetch_one=True)
    
    if not user:
        return MessageResponse(message=MENSAGEM_PADRAO)
    
    user_id = user["ID"]
    codigo = generate_numeric_code(6)
    data_expiracao = datetime.now(timezone.utc) + timedelta(minutes=15)
    
    # Limpar códigos expirados/antigos deste usuário
    cleanup_query = """
        DELETE FROM codigos_reset_senha
        WHERE usuario_id = :usuario_id AND (usado = 1 OR data_expiracao < :now)
    """
    execute_query(cleanup_query, {"usuario_id": user_id, "now": datetime.now(timezone.utc)}, commit=True)
    
    insert_query = """
        INSERT INTO codigos_reset_senha (usuario_id, codigo, data_expiracao)
        VALUES (:usuario_id, :codigo, :data_expiracao)
    """
    
    execute_query(
        insert_query,
        {"usuario_id": user_id, "codigo": codigo, "data_expiracao": data_expiracao},
        commit=True
    )

    send_reset_code_email(to_email=body.email, code=codigo)
    
    return MessageResponse(message=MENSAGEM_PADRAO)

@router.post("/reset-password", response_model=MessageResponse)
@limiter.limit("5/minute")
async def reset_password(request: Request, body: ResetPasswordRequest):
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
        {"email": body.email, "codigo": body.codigo},
        fetch_one=True
    )
    
    if not codigo_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código ou e-mail inválido"
        )
    
    codigo_id = codigo_data["ID"]
    usuario_id = codigo_data["USUARIO_ID"]
    data_expiracao = codigo_data["DATA_EXPIRACAO"]
    usado = codigo_data["USADO"]
    
    if usado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código já foi utilizado"
        )
    
    # Comparar como naive — Oracle retorna datetime sem timezone
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    exp = data_expiracao.replace(tzinfo=None) if hasattr(data_expiracao, 'tzinfo') and data_expiracao.tzinfo else data_expiracao
    if now_utc > exp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código expirou"
        )
    
    nova_senha_hash = get_password_hash(body.nova_senha)
    
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

# ============ ENDPOINTS DE APROVAÇÃO DE CADASTRO ============

@router.get("/pendentes")
async def listar_pendentes(
    current_user: dict = Depends(get_current_admin_user)
):
    """Lista usuários aguardando aprovação (admin only)"""
    query = """
        SELECT id, nome_completo, email, setor, data_cadastro
        FROM usuarios
        WHERE ativo = 0
        ORDER BY data_cadastro DESC
    """
    results = execute_query(query)
    
    return [
        {
            "id": row["ID"],
            "nome_completo": row["NOME_COMPLETO"],
            "email": row["EMAIL"],
            "setor": row["SETOR"],
            "data_cadastro": row["DATA_CADASTRO"]
        }
        for row in results
    ]

@router.put("/aprovar/{usuario_id}")
async def aprovar_usuario(
    usuario_id: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """Aprova um cadastro pendente (admin only)"""
    
    query = "SELECT id, nome_completo, email, ativo FROM usuarios WHERE id = :id"
    user = execute_query(query, {"id": usuario_id}, fetch_one=True)
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    
    if user["ATIVO"]:
        raise HTTPException(status_code=400, detail="Usuário já está ativo")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET ativo = 1 WHERE id = :id", {"id": usuario_id})
        conn.commit()
        cursor.close()
    
    return {"message": f"Usuário '{user['NOME_COMPLETO']}' aprovado com sucesso!"}

@router.put("/rejeitar/{usuario_id}")
async def rejeitar_usuario(
    usuario_id: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """Rejeita e remove um cadastro pendente (admin only)"""
    
    query = "SELECT id, nome_completo, ativo FROM usuarios WHERE id = :id"
    user = execute_query(query, {"id": usuario_id}, fetch_one=True)
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    
    if user["ATIVO"]:
        raise HTTPException(status_code=400, detail="Não é possível rejeitar um usuário já ativo")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM usuarios WHERE id = :id AND ativo = 0", {"id": usuario_id})
        conn.commit()
        cursor.close()
    
    return {"message": f"Cadastro de '{user['NOME_COMPLETO']}' rejeitado e removido."}