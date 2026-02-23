from fastapi import APIRouter, HTTPException, status, Depends
from typing import List
from datetime import datetime
from auth import get_current_user, get_current_admin_user
from database import execute_query, get_db_connection

router = APIRouter(prefix="/feedbacks", tags=["Feedbacks"])

CATEGORIAS_VALIDAS = ["ELOGIO", "SUGESTAO", "PROBLEMA", "OUTRO"]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def enviar_feedback(
    feedback: dict,
    current_user: dict = Depends(get_current_user)
):
    """Envia um feedback (opcionalmente anônimo)"""
    
    categoria = feedback.get("categoria", "").upper()
    mensagem = feedback.get("mensagem", "").strip()
    anonimo = feedback.get("anonimo", False)
    
    if categoria not in CATEGORIAS_VALIDAS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Categoria inválida. Use: {', '.join(CATEGORIAS_VALIDAS)}"
        )
    
    if not mensagem or len(mensagem) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mensagem deve ter pelo menos 5 caracteres"
        )
    
    if len(mensagem) > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mensagem deve ter no máximo 1000 caracteres"
        )
    
    usuario_id = None if anonimo else current_user["id"]
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO feedbacks (usuario_id, categoria, mensagem, anonimo)
            VALUES (:usuario_id, :categoria, :mensagem, :anonimo)
        """, {
            "usuario_id": usuario_id,
            "categoria": categoria,
            "mensagem": mensagem,
            "anonimo": 1 if anonimo else 0
        })
        conn.commit()
        cursor.close()
    
    return {"message": "Feedback enviado com sucesso! Obrigado 🍕"}


@router.get("/")
async def listar_feedbacks(
    current_user: dict = Depends(get_current_admin_user)
):
    """Lista todos os feedbacks (admin only)"""
    
    query = """
        SELECT f.id, f.usuario_id, f.categoria, f.mensagem, f.anonimo, f.data_criacao,
               u.nome_completo
        FROM feedbacks f
        LEFT JOIN usuarios u ON f.usuario_id = u.id
        ORDER BY f.data_criacao DESC
    """
    
    results = execute_query(query)
    
    feedbacks = []
    for row in results:
        feedbacks.append({
            "id": row["ID"],
            "categoria": row["CATEGORIA"],
            "mensagem": row["MENSAGEM"],
            "anonimo": bool(row["ANONIMO"]),
            "data_criacao": row["DATA_CRIACAO"],
            "usuario_nome": row["NOME_COMPLETO"] if not row["ANONIMO"] else "Anônimo"
        })
    
    return feedbacks
