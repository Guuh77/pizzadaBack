from fastapi import APIRouter, HTTPException, status, Depends
from typing import List
from models import (
    PedidoCreate, PedidoResponse, PedidoUpdate,
    ItemPedidoResponse, DashboardResponse, EstatisticasPizza
)
from auth import get_current_user, get_current_admin_user
from database import execute_query, get_db_connection

router = APIRouter(prefix="/pedidos", tags=["Pedidos"])

@router.post("/", response_model=PedidoResponse, status_code=status.HTTP_201_CREATED)
async def criar_pedido(
    pedido: PedidoCreate,
    current_user: dict = Depends(get_current_user)
):
    """Cria um novo pedido para o usuário logado"""
    
    # Verificar se evento existe e está aberto
    evento_query = """
        SELECT id, status, data_limite, tipo
        FROM eventos
        WHERE id = :evento_id AND status = 'ABERTO'
    """
    evento = execute_query(evento_query, {"evento_id": pedido.evento_id}, fetch_one=True)
    
    if not evento:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Evento não encontrado ou não está aberto para pedidos"
        )
    
    # Verificar acesso se for evento relâmpago
    tipo_evento = evento[3] if len(evento) > 3 else 'NORMAL'
    if tipo_evento == 'RELAMPAGO' and not current_user["is_admin"]:
        access_query = """
            SELECT 1 FROM evento_acessos 
            WHERE evento_id = :evento_id AND usuario_id = :usuario_id
        """
        has_access = execute_query(
            access_query, 
            {"evento_id": pedido.evento_id, "usuario_id": current_user["id"]}, 
            fetch_one=True
        )
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para participar deste evento relâmpago"
            )

    # Verificar se usuário já tem pedido neste evento
    check_pedido = """
        SELECT id FROM pedidos
        WHERE evento_id = :evento_id AND usuario_id = :usuario_id
    """
    existing_pedido = execute_query(
        check_pedido,
        {"evento_id": pedido.evento_id, "usuario_id": current_user["id"]},
        fetch_one=True
    )
    
    if existing_pedido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Você já tem um pedido neste evento. Edite ou cancele o pedido existente."
        )
    
    # Buscar preços dos sabores e calcular total
    valor_total = 0.0
    itens_validados = []
    
    for item in pedido.itens:
        sabor_query = """
            SELECT id, nome, preco_pedaco, ativo
            FROM sabores_pizza
            WHERE id = :sabor_id AND ativo = 1
        """
        sabor = execute_query(sabor_query, {"sabor_id": item.sabor_id}, fetch_one=True)
        
        if not sabor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Sabor com ID {item.sabor_id} não encontrado ou inativo"
            )
        
        preco_unitario = float(sabor[2])
        subtotal = preco_unitario * item.quantidade
        valor_total += subtotal
        
        itens_validados.append({
            "sabor_id": item.sabor_id,
            "sabor_nome": sabor[1],
            "quantidade": item.quantidade,
            "preco_unitario": preco_unitario,
            "subtotal": subtotal
        })
    
    valor_frete = 1.00
    
    # Inserir pedido e itens
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Inserir pedido
        insert_pedido_query = """
            INSERT INTO pedidos (evento_id, usuario_id, valor_total, valor_frete, status)
            VALUES (:evento_id, :usuario_id, :valor_total, :valor_frete, 'PENDENTE')
        """
        cursor.execute(
            insert_pedido_query,
            {
                "evento_id": pedido.evento_id,
                "usuario_id": current_user["id"],
                "valor_total": valor_total,
                "valor_frete": valor_frete
            }
        )
        
        # Buscar ID do pedido criado
        cursor.execute(
            "SELECT id FROM pedidos WHERE evento_id = :evento_id AND usuario_id = :usuario_id",
            {"evento_id": pedido.evento_id, "usuario_id": current_user["id"]}
        )
        pedido_id = cursor.fetchone()[0]
        
        # Inserir itens do pedido
        insert_item_query = """
            INSERT INTO itens_pedido (pedido_id, sabor_id, quantidade, preco_unitario, subtotal)
            VALUES (:pedido_id, :sabor_id, :quantidade, :preco_unitario, :subtotal)
        """
        
        for item in itens_validados:
            cursor.execute(
                insert_item_query,
                {
                    "pedido_id": pedido_id,
                    "sabor_id": item["sabor_id"],
                    "quantidade": item["quantidade"],
                    "preco_unitario": item["preco_unitario"],
                    "subtotal": item["subtotal"]
                }
            )
        
        conn.commit()
        cursor.close()
    
    # Buscar pedido completo para retornar
    return await obter_pedido(pedido_id, current_user)

@router.get("/meus-pedidos", response_model=List[PedidoResponse])
async def listar_meus_pedidos(
    current_user: dict = Depends(get_current_user)
):
    """Lista todos os pedidos do usuário logado"""
    
    query = """
        SELECT p.id
        FROM pedidos p
        WHERE p.usuario_id = :usuario_id
        ORDER BY p.data_pedido DESC
    """
    
    results = execute_query(query, {"usuario_id": current_user["id"]})
    
    pedidos = []
    for row in results:
        pedido = await obter_pedido(row["ID"], current_user)
        pedidos.append(pedido)
    
    return pedidos

@router.get("/{pedido_id}", response_model=PedidoResponse)
async def obter_pedido(
    pedido_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Obtém detalhes de um pedido específico"""
    
    # Buscar pedido
    pedido_query = """
        SELECT p.id, p.evento_id, p.usuario_id, p.valor_total, p.valor_frete, 
               p.status, p.data_pedido, u.nome_completo, u.setor
        FROM pedidos p
        JOIN usuarios u ON p.usuario_id = u.id
        WHERE p.id = :pedido_id
    """
    
    pedido = execute_query(pedido_query, {"pedido_id": pedido_id}, fetch_one=True)
    
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pedido não encontrado"
        )
    
    # Verificar permissão (usuário pode ver apenas seus pedidos, admin vê todos)
    if pedido[2] != current_user["id"] and not current_user["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para ver este pedido"
        )
    
    # Buscar itens do pedido
    itens_query = """
        SELECT ip.id, ip.sabor_id, sp.nome as sabor_nome, ip.quantidade, 
               ip.preco_unitario, ip.subtotal
        FROM itens_pedido ip
        JOIN sabores_pizza sp ON ip.sabor_id = sp.id
        WHERE ip.pedido_id = :pedido_id
    """
    
    itens = execute_query(itens_query, {"pedido_id": pedido_id})
    
    return PedidoResponse(
        id=pedido[0],
        evento_id=pedido[1],
        usuario_id=pedido[2],
        usuario_nome=pedido[7],
        usuario_setor=pedido[8],
        valor_total=float(pedido[3]),
        valor_frete=float(pedido[4]),
        status=pedido[5],
        data_pedido=pedido[6],
        itens=[
            ItemPedidoResponse(
                id=item["ID"],
                sabor_id=item["SABOR_ID"],
                sabor_nome=item["SABOR_NOME"],
                quantidade=item["QUANTIDADE"],
                preco_unitario=float(item["PRECO_UNITARIO"]),
                subtotal=float(item["SUBTOTAL"])
            )
            for item in itens
        ]
    )

@router.get("/evento/{evento_id}/todos", response_model=List[PedidoResponse])
async def listar_pedidos_evento(
    evento_id: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """Lista todos os pedidos de um evento (apenas admin)"""
    
    query = """
        SELECT p.id
        FROM pedidos p
        WHERE p.evento_id = :evento_id
        ORDER BY p.data_pedido DESC
    """
    
    results = execute_query(query, {"evento_id": evento_id})
    
    pedidos = []
    for row in results:
        pedido = await obter_pedido(row["ID"], current_user)
        pedidos.append(pedido)
    
    return pedidos

@router.put("/{pedido_id}", response_model=PedidoResponse)
async def atualizar_pedido(
    pedido_id: int,
    pedido_update: PedidoUpdate,
    current_user: dict = Depends(get_current_admin_user)
):
    """Atualiza status de um pedido (apenas admin)"""
    
    # Verificar se pedido existe
    check_query = "SELECT id FROM pedidos WHERE id = :pedido_id"
    existing = execute_query(check_query, {"pedido_id": pedido_id}, fetch_one=True)
    
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pedido não encontrado"
        )
    
    # Atualizar status
    update_query = """
        UPDATE pedidos
        SET status = :status
        WHERE id = :pedido_id
    """
    
    execute_query(
        update_query,
        {"status": pedido_update.status, "pedido_id": pedido_id},
        commit=True
    )
    
    return await obter_pedido(pedido_id, current_user)

@router.put("/{pedido_id}/editar", response_model=PedidoResponse)
async def editar_meu_pedido(
    pedido_id: int,
    pedido_novo: PedidoCreate,
    current_user: dict = Depends(get_current_user)
):
    """Permite usuário editar seu próprio pedido"""
    
    # Verificar se pedido existe e pertence ao usuário
    check_query = """
        SELECT p.id, p.usuario_id, e.status
        FROM pedidos p
        JOIN eventos e ON p.evento_id = e.id
        WHERE p.id = :pedido_id
    """
    
    pedido = execute_query(check_query, {"pedido_id": pedido_id}, fetch_one=True)
    
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pedido não encontrado"
        )
    
    # Verificar permissão
    if pedido[1] != current_user["id"] and not current_user["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para editar este pedido"
        )
    
    # Verificar se evento ainda está aberto
    if pedido[2] != 'ABERTO':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível editar pedido de evento que não está mais aberto"
        )
    
    # Deletar pedido antigo
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pedidos WHERE id = :pedido_id", {"pedido_id": pedido_id})
        conn.commit()
        cursor.close()
    
    # Criar novo pedido (reutiliza a lógica de criar_pedido)
    # Buscar preços dos sabores e calcular total
    valor_total = 0.0
    itens_validados = []
    
    for item in pedido_novo.itens:
        sabor_query = """
            SELECT id, nome, preco_pedaco, ativo
            FROM sabores_pizza
            WHERE id = :sabor_id AND ativo = 1
        """
        sabor = execute_query(sabor_query, {"sabor_id": item.sabor_id}, fetch_one=True)
        
        if not sabor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Sabor com ID {item.sabor_id} não encontrado ou inativo"
            )
        
        preco_unitario = float(sabor[2])
        subtotal = preco_unitario * item.quantidade
        valor_total += subtotal
        
        itens_validados.append({
            "sabor_id": item.sabor_id,
            "sabor_nome": sabor[1],
            "quantidade": item.quantidade,
            "preco_unitario": preco_unitario,
            "subtotal": subtotal
        })
    
    valor_frete = 1.00
    
    # Inserir novo pedido
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        insert_pedido_query = """
            INSERT INTO pedidos (evento_id, usuario_id, valor_total, valor_frete, status)
            VALUES (:evento_id, :usuario_id, :valor_total, :valor_frete, 'PENDENTE')
        """
        cursor.execute(
            insert_pedido_query,
            {
                "evento_id": pedido_novo.evento_id,
                "usuario_id": current_user["id"],
                "valor_total": valor_total,
                "valor_frete": valor_frete
            }
        )
        
        # Buscar ID do novo pedido
        cursor.execute(
            "SELECT id FROM pedidos WHERE evento_id = :evento_id AND usuario_id = :usuario_id ORDER BY data_pedido DESC FETCH FIRST 1 ROWS ONLY",
            {"evento_id": pedido_novo.evento_id, "usuario_id": current_user["id"]}
        )
        novo_pedido_id = cursor.fetchone()[0]
        
        # Inserir itens
        insert_item_query = """
            INSERT INTO itens_pedido (pedido_id, sabor_id, quantidade, preco_unitario, subtotal)
            VALUES (:pedido_id, :sabor_id, :quantidade, :preco_unitario, :subtotal)
        """
        
        for item in itens_validados:
            cursor.execute(
                insert_item_query,
                {
                    "pedido_id": novo_pedido_id,
                    "sabor_id": item["sabor_id"],
                    "quantidade": item["quantidade"],
                    "preco_unitario": item["preco_unitario"],
                    "subtotal": item["subtotal"]
                }
            )
        
        conn.commit()
        cursor.close()
    
    return await obter_pedido(novo_pedido_id, current_user)

@router.put("/{pedido_id}/admin-editar", response_model=PedidoResponse)
async def admin_editar_pedido(
    pedido_id: int,
    pedido_novo: PedidoCreate,
    current_user: dict = Depends(get_current_admin_user)
):
    """Permite ADMIN editar qualquer pedido (de qualquer usuário)"""
    
    # Verificar se pedido existe
    check_query = """
        SELECT p.id, p.usuario_id, e.status, p.evento_id
        FROM pedidos p
        JOIN eventos e ON p.evento_id = e.id
        WHERE p.id = :pedido_id
    """
    
    pedido = execute_query(check_query, {"pedido_id": pedido_id}, fetch_one=True)
    
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pedido não encontrado"
        )
    
    original_usuario_id = pedido[1]
    original_evento_id = pedido[3]
    
    # Admin pode editar mesmo se evento estiver FECHADO
    
    # Buscar preços dos sabores e calcular total
    valor_total = 0.0
    itens_validados = []
    
    for item in pedido_novo.itens:
        sabor_query = """
            SELECT id, nome, preco_pedaco, ativo
            FROM sabores_pizza
            WHERE id = :sabor_id AND ativo = 1
        """
        sabor = execute_query(sabor_query, {"sabor_id": item.sabor_id}, fetch_one=True)
        
        if not sabor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Sabor com ID {item.sabor_id} não encontrado ou inativo"
            )
        
        preco_unitario = float(sabor[2])
        subtotal = preco_unitario * item.quantidade
        valor_total += subtotal
        
        itens_validados.append({
            "sabor_id": item.sabor_id,
            "sabor_nome": sabor[1],
            "quantidade": item.quantidade,
            "preco_unitario": preco_unitario,
            "subtotal": subtotal
        })
    
    valor_frete = 1.00
    
    # Deletar itens antigos e atualizar pedido
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Deletar itens antigos
        cursor.execute("DELETE FROM itens_pedido WHERE pedido_id = :pedido_id", {"pedido_id": pedido_id})
        
        # Atualizar valor do pedido
        cursor.execute(
            "UPDATE pedidos SET valor_total = :valor_total WHERE id = :pedido_id",
            {"valor_total": valor_total, "pedido_id": pedido_id}
        )
        
        # Inserir novos itens
        insert_item_query = """
            INSERT INTO itens_pedido (pedido_id, sabor_id, quantidade, preco_unitario, subtotal)
            VALUES (:pedido_id, :sabor_id, :quantidade, :preco_unitario, :subtotal)
        """
        
        for item in itens_validados:
            cursor.execute(
                insert_item_query,
                {
                    "pedido_id": pedido_id,
                    "sabor_id": item["sabor_id"],
                    "quantidade": item["quantidade"],
                    "preco_unitario": item["preco_unitario"],
                    "subtotal": item["subtotal"]
                }
            )
        
        conn.commit()
        cursor.close()
    
    return await obter_pedido(pedido_id, current_user)

@router.post("/admin-criar", response_model=PedidoResponse, status_code=status.HTTP_201_CREATED)
async def admin_criar_pedido(
    usuario_id: int,
    pedido: PedidoCreate,
    current_user: dict = Depends(get_current_admin_user)
):
    """Permite ADMIN criar pedido em nome de outro usuário (ignora status do evento)"""
    
    # Verificar se evento existe (não verifica se está aberto)
    evento_query = """
        SELECT id, status
        FROM eventos
        WHERE id = :evento_id
    """
    evento = execute_query(evento_query, {"evento_id": pedido.evento_id}, fetch_one=True)
    
    if not evento:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Evento não encontrado"
        )
    
    # Verificar se usuário existe
    usuario_query = """
        SELECT id, nome_completo FROM usuarios WHERE id = :usuario_id AND ativo = 1
    """
    usuario = execute_query(usuario_query, {"usuario_id": usuario_id}, fetch_one=True)
    
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário não encontrado ou inativo"
        )
    
    # Verificar se usuário já tem pedido neste evento
    check_pedido = """
        SELECT id FROM pedidos
        WHERE evento_id = :evento_id AND usuario_id = :usuario_id
    """
    existing_pedido = execute_query(
        check_pedido,
        {"evento_id": pedido.evento_id, "usuario_id": usuario_id},
        fetch_one=True
    )
    
    if existing_pedido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este usuário já tem um pedido neste evento"
        )
    
    # Buscar preços dos sabores e calcular total
    valor_total = 0.0
    itens_validados = []
    
    for item in pedido.itens:
        sabor_query = """
            SELECT id, nome, preco_pedaco, ativo
            FROM sabores_pizza
            WHERE id = :sabor_id AND ativo = 1
        """
        sabor = execute_query(sabor_query, {"sabor_id": item.sabor_id}, fetch_one=True)
        
        if not sabor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Sabor com ID {item.sabor_id} não encontrado ou inativo"
            )
        
        preco_unitario = float(sabor[2])
        subtotal = preco_unitario * item.quantidade
        valor_total += subtotal
        
        itens_validados.append({
            "sabor_id": item.sabor_id,
            "sabor_nome": sabor[1],
            "quantidade": item.quantidade,
            "preco_unitario": preco_unitario,
            "subtotal": subtotal
        })
    
    valor_frete = 1.00
    
    # Inserir pedido e itens
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Inserir pedido para o usuário especificado
        insert_pedido_query = """
            INSERT INTO pedidos (evento_id, usuario_id, valor_total, valor_frete, status)
            VALUES (:evento_id, :usuario_id, :valor_total, :valor_frete, 'PENDENTE')
        """
        cursor.execute(
            insert_pedido_query,
            {
                "evento_id": pedido.evento_id,
                "usuario_id": usuario_id,
                "valor_total": valor_total,
                "valor_frete": valor_frete
            }
        )
        
        # Buscar ID do pedido criado
        cursor.execute(
            "SELECT id FROM pedidos WHERE evento_id = :evento_id AND usuario_id = :usuario_id ORDER BY data_pedido DESC FETCH FIRST 1 ROWS ONLY",
            {"evento_id": pedido.evento_id, "usuario_id": usuario_id}
        )
        pedido_id = cursor.fetchone()[0]
        
        # Inserir itens do pedido
        insert_item_query = """
            INSERT INTO itens_pedido (pedido_id, sabor_id, quantidade, preco_unitario, subtotal)
            VALUES (:pedido_id, :sabor_id, :quantidade, :preco_unitario, :subtotal)
        """
        
        for item in itens_validados:
            cursor.execute(
                insert_item_query,
                {
                    "pedido_id": pedido_id,
                    "sabor_id": item["sabor_id"],
                    "quantidade": item["quantidade"],
                    "preco_unitario": item["preco_unitario"],
                    "subtotal": item["subtotal"]
                }
            )
        
        conn.commit()
        cursor.close()
    
    # Buscar pedido completo para retornar
    return await obter_pedido(pedido_id, current_user)

@router.delete("/{pedido_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancelar_pedido(
    pedido_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Cancela um pedido (usuário pode cancelar apenas o próprio)"""
    
    # Verificar se pedido existe e pertence ao usuário
    check_query = """
        SELECT p.id, p.usuario_id, e.status
        FROM pedidos p
        JOIN eventos e ON p.evento_id = e.id
        WHERE p.id = :pedido_id
    """
    
    pedido = execute_query(check_query, {"pedido_id": pedido_id}, fetch_one=True)
    
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pedido não encontrado"
        )
    
    # Verificar permissão
    if pedido[1] != current_user["id"] and not current_user["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para cancelar este pedido"
        )
    
    # Verificar se evento ainda está aberto
    if pedido[2] != 'ABERTO':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível cancelar pedido de evento que não está mais aberto"
        )
    
    # Deletar pedido (cascade deleta os itens)
    delete_query = "DELETE FROM pedidos WHERE id = :pedido_id"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(delete_query, {"pedido_id": pedido_id})
        conn.commit()
        cursor.close()
    
    return None
