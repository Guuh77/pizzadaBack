from fastapi import APIRouter, HTTPException, status, Depends
from typing import List
from models import SaborPizzaCreate, SaborPizzaUpdate, SaborPizzaResponse
from auth import get_current_admin_user, get_current_user
from database import execute_query, get_db_connection

router = APIRouter(prefix="/sabores", tags=["Sabores de Pizza"])

@router.get("/", response_model=List[SaborPizzaResponse])
async def listar_sabores(
    apenas_ativos: bool = True,
    current_user: dict = Depends(get_current_user)
):
    """Lista todos os sabores de pizza"""
    
    query = "SELECT id, nome, preco_pedaco, ativo, data_cadastro, tipo, descricao FROM sabores_pizza"
    
    if apenas_ativos:
        query += " WHERE ativo = 1"
    
    query += " ORDER BY nome"
    
    results = execute_query(query)
    
    return [
        SaborPizzaResponse(
            id=row["ID"],
            nome=row["NOME"],
            preco_pedaco=float(row["PRECO_PEDACO"]),
            ativo=bool(row["ATIVO"]),
            data_cadastro=row["DATA_CADASTRO"],
            tipo=row.get("TIPO", "SALGADA"),
            descricao=row.get("DESCRICAO")
        )
        for row in results
    ]

@router.get("/{sabor_id}", response_model=SaborPizzaResponse)
async def obter_sabor(
    sabor_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Obtém um sabor específico"""
    
    query = """
        SELECT id, nome, preco_pedaco, ativo, data_cadastro, tipo, descricao
        FROM sabores_pizza
        WHERE id = :sabor_id
    """
    
    result = execute_query(query, {"sabor_id": sabor_id}, fetch_one=True)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sabor não encontrado"
        )
    
    return SaborPizzaResponse(
        id=result[0],
        nome=result[1],
        preco_pedaco=float(result[2]),
        ativo=bool(result[3]),
        data_cadastro=result[4],
        tipo=result[5] if len(result) > 5 else "SALGADA",
        descricao=result[6] if len(result) > 6 else None
    )

@router.post("/", response_model=SaborPizzaResponse, status_code=status.HTTP_201_CREATED)
async def criar_sabor(
    sabor: SaborPizzaCreate,
    current_user: dict = Depends(get_current_admin_user)
):
    """Cria um novo sabor de pizza (apenas admin)"""
    
    # Verificar se sabor já existe
    check_query = "SELECT id FROM sabores_pizza WHERE UPPER(nome) = UPPER(:nome)"
    existing = execute_query(check_query, {"nome": sabor.nome}, fetch_one=True)
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Já existe um sabor com este nome"
        )
    
    # Inserir sabor
    insert_query = """
        INSERT INTO sabores_pizza (nome, preco_pedaco, tipo, descricao)
        VALUES (:nome, :preco, :tipo, :descricao)
    """
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            insert_query,
            {"nome": sabor.nome, "preco": sabor.preco_pedaco, "tipo": sabor.tipo, "descricao": sabor.descricao}
        )
        conn.commit()
        
        # Buscar o sabor criado
        select_query = """
            SELECT id, nome, preco_pedaco, ativo, data_cadastro, tipo, descricao
            FROM sabores_pizza
            WHERE UPPER(nome) = UPPER(:nome)
        """
        cursor.execute(select_query, {"nome": sabor.nome})
        result = cursor.fetchone()
        cursor.close()
    
    return SaborPizzaResponse(
        id=result[0],
        nome=result[1],
        preco_pedaco=float(result[2]),
        ativo=bool(result[3]),
        data_cadastro=result[4],
        tipo=result[5] if len(result) > 5 else "SALGADA",
        descricao=result[6] if len(result) > 6 else None
    )

@router.put("/{sabor_id}", response_model=SaborPizzaResponse)
async def atualizar_sabor(
    sabor_id: int,
    sabor: SaborPizzaUpdate,
    current_user: dict = Depends(get_current_admin_user)
):
    """Atualiza um sabor de pizza (apenas admin)"""
    
    # Verificar se sabor existe
    check_query = "SELECT id FROM sabores_pizza WHERE id = :sabor_id"
    existing = execute_query(check_query, {"sabor_id": sabor_id}, fetch_one=True)
    
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sabor não encontrado"
        )
    
    # Construir query de atualização dinamicamente
    updates = []
    params = {"sabor_id": sabor_id}
    
    if sabor.nome is not None:
        updates.append("nome = :nome")
        params["nome"] = sabor.nome
    
    if sabor.preco_pedaco is not None:
        updates.append("preco_pedaco = :preco")
        params["preco"] = sabor.preco_pedaco

    if sabor.tipo is not None:
        updates.append("tipo = :tipo")
        params["tipo"] = sabor.tipo

    if sabor.descricao is not None:
        updates.append("descricao = :descricao")
        params["descricao"] = sabor.descricao
    
    if sabor.ativo is not None:
        updates.append("ativo = :ativo")
        params["ativo"] = 1 if sabor.ativo else 0
    
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum campo para atualizar"
        )
    
    update_query = f"""
        UPDATE sabores_pizza
        SET {', '.join(updates)}
        WHERE id = :sabor_id
    """
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(update_query, params)
        conn.commit()
        
        # Buscar sabor atualizado
        select_query = """
            SELECT id, nome, preco_pedaco, ativo, data_cadastro, tipo, descricao
            FROM sabores_pizza
            WHERE id = :sabor_id
        """
        cursor.execute(select_query, {"sabor_id": sabor_id})
        result = cursor.fetchone()
        cursor.close()
    
    return SaborPizzaResponse(
        id=result[0],
        nome=result[1],
        preco_pedaco=float(result[2]),
        ativo=bool(result[3]),
        data_cadastro=result[4],
        tipo=result[5] if len(result) > 5 else "SALGADA",
        descricao=result[6] if len(result) > 6 else None
    )

@router.delete("/{sabor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deletar_sabor(
    sabor_id: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """Desativa um sabor de pizza (soft delete) (apenas admin)"""
    
    query = "UPDATE sabores_pizza SET ativo = 0 WHERE id = :sabor_id"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, {"sabor_id": sabor_id})
        
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sabor não encontrado"
            )
        
        conn.commit()
        cursor.close()
    
    return None
