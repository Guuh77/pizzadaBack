from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from auth import get_current_admin_user
from database import execute_query, get_db_connection
from models import UsuarioResponse

router = APIRouter(prefix="/admin", tags=["Administração e Auditoria"])



class UsuarioStatusEdit(BaseModel):
    ativo: int

class UsuarioEdit(BaseModel):
    is_admin: bool
    setor: str

@router.get("/usuarios/todos", response_model=List[UsuarioResponse])
async def listar_todos_usuarios(current_admin: dict = Depends(get_current_admin_user)):
    """Lista todos os usuários (ativos e inativos) - Apenas Admin"""
    query = """
        SELECT id, nome_completo, email, setor, is_admin, ativo, data_cadastro
        FROM usuarios
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

@router.put("/usuarios/{usuario_id}/status")
async def alterar_status_usuario(
    usuario_id: int, 
    status_update: UsuarioStatusEdit, 
    current_admin: dict = Depends(get_current_admin_user)
):
    """Ativa ou inativa um usuário"""
    if usuario_id == current_admin["id"]:
        raise HTTPException(status_code=400, detail="Você não pode alterar seu próprio status")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET ativo = :ativo WHERE id = :id", {
            "ativo": status_update.ativo,
            "id": usuario_id
        })
        if cursor.rowcount == 0:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        
        # Log audit
        cursor.execute("""
            INSERT INTO auditoria_logs (usuario_id, acao, detalhes)
            VALUES (:admin_id, :acao, :detalhes)
        """, {
            "admin_id": current_admin["id"],
            "acao": "ALTERAR_STATUS_USUARIO",
            "detalhes": f"Alterou usuario ID {int(usuario_id)} para ativo={int(status_update.ativo)}"
        })
        conn.commit()
    
    return {"message": "Status atualizado com sucesso"}

@router.put("/usuarios/{usuario_id}")
async def editar_usuario(
    usuario_id: int, 
    edit_data: UsuarioEdit, 
    current_admin: dict = Depends(get_current_admin_user)
):
    """Edita dados básicos de um usuário"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE usuarios 
            SET setor = :setor, is_admin = :is_admin 
            WHERE id = :id
        """, {
            "setor": edit_data.setor,
            "is_admin": 1 if edit_data.is_admin else 0,
            "id": usuario_id
        })
        if cursor.rowcount == 0:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
            
        # Log audit
        cursor.execute("""
            INSERT INTO auditoria_logs (usuario_id, acao, detalhes)
            VALUES (:admin_id, :acao, :detalhes)
        """, {
            "admin_id": current_admin["id"],
            "acao": "EDITAR_USUARIO",
            "detalhes": f"Editou usuario ID {int(usuario_id)} (setor={str(edit_data.setor)[:50].replace(chr(10), '')}, admin={bool(edit_data.is_admin)})"
        })
        conn.commit()
        
    return {"message": "Usuário atualizado com sucesso"}

