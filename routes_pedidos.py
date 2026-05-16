from fastapi import APIRouter, HTTPException, status, Depends
from typing import List
from models import (
    PedidoCreate, PedidoResponse, PedidoUpdate,
    ItemPedidoResponse, DashboardResponse, EstatisticasPizza
)
from auth import get_current_user, get_current_admin_user
from database import execute_query, get_db_connection
from routes_auth import compute_is_premium

router = APIRouter(prefix="/pedidos", tags=["Pedidos"])


def _validar_e_precificar_itens(itens):
    """Valida e calcula preços de todos os itens em uma única query (evita N+1).
    
    Retorna (valor_total, itens_validados) ou levanta HTTPException.
    """
    if not itens:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pedido deve ter pelo menos 1 item"
        )
    
    # Coletar IDs únicos
    sabor_ids = list(set(item.sabor_id for item in itens))
    
    # Batch query: busca todos os sabores de uma vez
    placeholders = ", ".join(f":sid{i}" for i in range(len(sabor_ids)))
    params = {f"sid{i}": sid for i, sid in enumerate(sabor_ids)}
    
    sabores_query = f"""
        SELECT id, nome, preco_pedaco
        FROM sabores_pizza
        WHERE id IN ({placeholders}) AND ativo = 1
    """
    sabores_result = execute_query(sabores_query, params)
    sabores_map = {s["ID"]: s for s in sabores_result}
    
    # Validar e calcular
    valor_total = 0.0
    itens_validados = []
    
    for item in itens:
        sabor = sabores_map.get(item.sabor_id)
        if not sabor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Sabor com ID {item.sabor_id} não encontrado ou inativo"
            )
        
        preco_unitario = float(sabor["PRECO_PEDACO"])
        subtotal = preco_unitario * item.quantidade
        valor_total += subtotal
        
        itens_validados.append({
            "sabor_id": item.sabor_id,
            "sabor_nome": sabor["NOME"],
            "quantidade": item.quantidade,
            "preco_unitario": preco_unitario,
            "subtotal": subtotal
        })
    
    return valor_total, itens_validados

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
    tipo_evento = evento.get("TIPO", "NORMAL")
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
    
    # Buscar preços dos sabores e calcular total (batch - 1 query em vez de N)
    valor_total, itens_validados = _validar_e_precificar_itens(pedido.itens)
    
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
    
    # Single JOIN query instead of N+1
    query = """
        SELECT p.id, p.evento_id, p.usuario_id, p.valor_total, p.valor_frete,
               p.status, p.data_pedido, u.nome_completo, u.setor,
               ip.id as item_id, ip.sabor_id, sp.nome as sabor_nome,
               ip.quantidade, ip.preco_unitario, ip.subtotal
        FROM pedidos p
        JOIN usuarios u ON p.usuario_id = u.id
        LEFT JOIN itens_pedido ip ON ip.pedido_id = p.id
        LEFT JOIN sabores_pizza sp ON ip.sabor_id = sp.id
        WHERE p.usuario_id = :usuario_id
        ORDER BY p.data_pedido DESC, p.id, ip.id
    """
    
    results = execute_query(query, {"usuario_id": current_user["id"]})
    
    # Group rows by pedido_id
    pedidos_map = {}
    for row in results:
        pid = row["ID"]
        if pid not in pedidos_map:
            pedidos_map[pid] = {
                "pedido": row,
                "itens": []
            }
        if row["ITEM_ID"]:
            pedidos_map[pid]["itens"].append(row)
    
    pedidos = []
    for pid, data in pedidos_map.items():
        p = data["pedido"]
        uid = p["USUARIO_ID"]
            
        pedidos.append(PedidoResponse(
            id=p["ID"],
            evento_id=p["EVENTO_ID"],
            usuario_id=uid,
            usuario_nome=p["NOME_COMPLETO"],
            usuario_setor=p["SETOR"],
            is_premium=False,
            valor_total=float(p["VALOR_TOTAL"]),
            valor_frete=float(p["VALOR_FRETE"]),
            status=p["STATUS"],
            data_pedido=p["DATA_PEDIDO"],
            itens=[
                ItemPedidoResponse(
                    id=item["ITEM_ID"],
                    sabor_id=item["SABOR_ID"],
                    sabor_nome=item["SABOR_NOME"],
                    quantidade=item["QUANTIDADE"],
                    preco_unitario=float(item["PRECO_UNITARIO"]),
                    subtotal=float(item["SUBTOTAL"])
                )
                for item in data["itens"]
            ]
        ))
    
    return pedidos

@router.get("/meus-favoritos")
async def listar_meus_favoritos(
    current_user: dict = Depends(get_current_user)
):
    """Retorna os sabores mais pedidos pelo usuário (top 3)"""
    
    query = """
        SELECT sp.id as sabor_id, sp.nome as sabor_nome, sp.preco_pedaco,
               SUM(ip.quantidade) as total_pedacos,
               COUNT(DISTINCT p.evento_id) as total_eventos
        FROM itens_pedido ip
        JOIN pedidos p ON ip.pedido_id = p.id
        JOIN sabores_pizza sp ON ip.sabor_id = sp.id
        WHERE p.usuario_id = :usuario_id
        GROUP BY sp.id, sp.nome, sp.preco_pedaco
        ORDER BY total_pedacos DESC
        FETCH FIRST 3 ROWS ONLY
    """
    
    results = execute_query(query, {"usuario_id": current_user["id"]})
    
    favoritos = []
    for row in results:
        favoritos.append({
            "sabor_id": row["SABOR_ID"],
            "sabor_nome": row["SABOR_NOME"],
            "preco_pedaco": float(row["PRECO_PEDACO"]),
            "total_pedacos": row["TOTAL_PEDACOS"],
            "total_eventos": row["TOTAL_EVENTOS"]
        })
    
    return favoritos

@router.get("/minhas-estatisticas")
async def minhas_estatisticas(
    current_user: dict = Depends(get_current_user)
):
    """Retorna estatísticas pessoais do usuário"""
    
    # Query separada para stats de pedidos (sem JOIN com itens para evitar multiplicação)
    pedidos_query = """
        SELECT 
            COUNT(DISTINCT evento_id) as total_pizzadas,
            COALESCE(SUM(valor_total + valor_frete), 0) as total_gasto,
            MIN(data_pedido) as primeiro_pedido,
            MAX(data_pedido) as ultimo_pedido
        FROM pedidos
        WHERE usuario_id = :usuario_id
    """
    pedidos_result = execute_query(pedidos_query, {"usuario_id": current_user["id"]}, fetch_one=True)
    
    # Query separada para stats de itens
    itens_query = """
        SELECT 
            COALESCE(SUM(ip.quantidade), 0) as total_pedacos,
            COUNT(DISTINCT ip.sabor_id) as sabores_diferentes
        FROM itens_pedido ip
        JOIN pedidos p ON ip.pedido_id = p.id
        WHERE p.usuario_id = :usuario_id
    """
    itens_result = execute_query(itens_query, {"usuario_id": current_user["id"]}, fetch_one=True)
    
    # Sabor favorito
    fav_query = """
        SELECT sp.nome, SUM(ip.quantidade) as total
        FROM itens_pedido ip
        JOIN pedidos p ON ip.pedido_id = p.id
        JOIN sabores_pizza sp ON ip.sabor_id = sp.id
        WHERE p.usuario_id = :usuario_id
        GROUP BY sp.nome
        ORDER BY total DESC
        FETCH FIRST 1 ROWS ONLY
    """
    fav_result = execute_query(fav_query, {"usuario_id": current_user["id"]}, fetch_one=True)
    
    # Participou de evento relâmpago?
    relampago_query = """
        SELECT COUNT(*) as total FROM pedidos p
        JOIN eventos e ON p.evento_id = e.id
        WHERE p.usuario_id = :usuario_id AND e.tipo = 'RELAMPAGO'
    """
    relampago = execute_query(relampago_query, {"usuario_id": current_user["id"]}, fetch_one=True)
    
    return {
        "total_pizzadas": pedidos_result["TOTAL_PIZZADAS"] or 0,
        "total_gasto": float(pedidos_result["TOTAL_GASTO"] or 0),
        "total_pedacos": itens_result["TOTAL_PEDACOS"] or 0,
        "primeiro_pedido": pedidos_result["PRIMEIRO_PEDIDO"],
        "ultimo_pedido": pedidos_result["ULTIMO_PEDIDO"],
        "sabores_diferentes": itens_result["SABORES_DIFERENTES"] or 0,
        "sabor_favorito": fav_result["NOME"] if fav_result else None,
        "participou_relampago": (relampago["TOTAL"] or 0) > 0
    }

@router.get("/minhas-conquistas")
async def minhas_conquistas(
    current_user: dict = Depends(get_current_user)
):
    """Calcula conquistas/badges do usuário"""
    
    # Query para pedidos (sem JOIN com itens para evitar multiplicação)
    pedidos_query = """
        SELECT 
            COUNT(DISTINCT evento_id) as total_pizzadas,
            COALESCE(SUM(valor_total + valor_frete), 0) as total_gasto
        FROM pedidos
        WHERE usuario_id = :usuario_id
    """
    pedidos_stats = execute_query(pedidos_query, {"usuario_id": current_user["id"]}, fetch_one=True)
    
    # Query para itens
    itens_query = """
        SELECT COUNT(DISTINCT ip.sabor_id) as sabores_diferentes
        FROM itens_pedido ip
        JOIN pedidos p ON ip.pedido_id = p.id
        WHERE p.usuario_id = :usuario_id
    """
    itens_stats = execute_query(itens_query, {"usuario_id": current_user["id"]}, fetch_one=True)
    
    total_pizzadas = pedidos_stats["TOTAL_PIZZADAS"] or 0
    total_gasto = float(pedidos_stats["TOTAL_GASTO"] or 0)
    sabores_diferentes = itens_stats["SABORES_DIFERENTES"] or 0
    
    # Sabor mais repetido
    fiel_query = """
        SELECT MAX(cnt) as total FROM (
            SELECT COUNT(DISTINCT p.evento_id) as cnt
            FROM itens_pedido ip
            JOIN pedidos p ON ip.pedido_id = p.id
            WHERE p.usuario_id = :usuario_id
            GROUP BY ip.sabor_id
        )
    """
    fiel = execute_query(fiel_query, {"usuario_id": current_user["id"]}, fetch_one=True)
    max_repeticoes = (fiel["TOTAL"] if fiel else 0) or 0
    
    # Relâmpago
    relampago_query = """
        SELECT COUNT(*) as total FROM pedidos p
        JOIN eventos e ON p.evento_id = e.id
        WHERE p.usuario_id = :usuario_id AND e.tipo = 'RELAMPAGO'
    """
    relampago = execute_query(relampago_query, {"usuario_id": current_user["id"]}, fetch_one=True)
    participou_relampago = (relampago["TOTAL"] or 0) > 0
    
    # Sabor favorito para badge especial
    fav_query = """
        SELECT sp.nome, SUM(ip.quantidade) as total
        FROM itens_pedido ip
        JOIN pedidos p ON ip.pedido_id = p.id
        JOIN sabores_pizza sp ON ip.sabor_id = sp.id
        WHERE p.usuario_id = :usuario_id
        GROUP BY sp.nome
        ORDER BY total DESC
        FETCH FIRST 1 ROWS ONLY
    """
    fav_result = execute_query(fav_query, {"usuario_id": current_user["id"]}, fetch_one=True)
    sabor_favorito = fav_result["NOME"] if fav_result else None
    
    badges = [
        # Participação
        {"id": "primeira_fatia", "nome": "Primeira Fatia", "descricao": "Fez seu primeiro pedido", "icone": "pizza", "desbloqueada": total_pizzadas >= 1, "condicao": "Fazer 1 pedido"},
        {"id": "trainee", "nome": "Trainee da Pizzada", "descricao": "Participou de 2 Pizzadas", "icone": "baby", "desbloqueada": total_pizzadas >= 2, "condicao": f"{total_pizzadas}/2 Pizzadas"},
        {"id": "amante", "nome": "Amante das Pizzadas", "descricao": "Participou de 3 Pizzadas", "icone": "heart", "desbloqueada": total_pizzadas >= 3, "condicao": f"{total_pizzadas}/3 Pizzadas"},
        {"id": "vip", "nome": "Cliente VIP da Pizzada", "descricao": "Participou de 5 Pizzadas", "icone": "trophy", "desbloqueada": total_pizzadas >= 5, "condicao": f"{total_pizzadas}/5 Pizzadas"},
        {"id": "lenda", "nome": "Lenda da Pizzada", "descricao": "Participou de 10 Pizzadas", "icone": "crown", "desbloqueada": total_pizzadas >= 10, "condicao": f"{total_pizzadas}/10 Pizzadas"},
        {"id": "deus_pizza", "nome": "Deus Pizza", "descricao": "Participou de 20+ Pizzadas", "icone": "flame", "desbloqueada": total_pizzadas >= 20, "condicao": f"{total_pizzadas}/20 Pizzadas"},
        
        # Exploração
        {"id": "explorador", "nome": "Explorador", "descricao": "Provou 5 sabores diferentes", "icone": "globe", "desbloqueada": sabores_diferentes >= 5, "condicao": f"{sabores_diferentes}/5 sabores"},
        {"id": "turista", "nome": "Turista dos Sabores", "descricao": "Provou 10 sabores diferentes", "icone": "map", "desbloqueada": sabores_diferentes >= 10, "condicao": f"{sabores_diferentes}/10 sabores"},
        
        # Fidelidade e gasto
        {"id": "fiel", "nome": "Fiel", "descricao": "Pediu o mesmo sabor em 3+ Pizzadas", "icone": "target", "desbloqueada": max_repeticoes >= 3, "condicao": f"Máx: {max_repeticoes}/3 repetições"},
        {"id": "investidor", "nome": "Investidor", "descricao": "Gastou mais de R$100 no total", "icone": "wallet", "desbloqueada": total_gasto >= 100, "condicao": f"R${total_gasto:.0f}/R$100"},
        
        # Especiais
        {"id": "relampago", "nome": "Relâmpago", "descricao": "Participou de uma Pizzada Relâmpago", "icone": "zap", "desbloqueada": participou_relampago, "condicao": "Participar de evento ⚡"},
        
        # Premium (VIP + Turista)
        {"id": "premium", "nome": "User Premium 👑", "descricao": "Veterano: 5 Pizzadas + 10 sabores diferentes", "icone": "crown", "desbloqueada": total_pizzadas >= 5 and sabores_diferentes >= 10, "condicao": f"{total_pizzadas}/5 Pizzadas + {sabores_diferentes}/10 sabores"},
    ]
    
    # Badge especial do sabor favorito
    if sabor_favorito:
        badges.append({
            "id": "sabor_alma", "nome": f"Fã de {sabor_favorito}", "descricao": f"Seu sabor favorito é {sabor_favorito}!", "icone": "star", "desbloqueada": True, "condicao": f"Sabor mais pedido: {sabor_favorito}"
        })
    
    return {
        "badges": badges,
        "total_desbloqueadas": sum(1 for b in badges if b["desbloqueada"]),
        "total_badges": len(badges)
    }

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
    if pedido["USUARIO_ID"] != current_user["id"] and not current_user["is_admin"]:
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
        id=pedido["ID"],
        evento_id=pedido["EVENTO_ID"],
        usuario_id=pedido["USUARIO_ID"],
        usuario_nome=pedido["NOME_COMPLETO"],
        usuario_setor=pedido["SETOR"],
        valor_total=float(pedido["VALOR_TOTAL"]),
        valor_frete=float(pedido["VALOR_FRETE"]),
        status=pedido["STATUS"],
        data_pedido=pedido["DATA_PEDIDO"],
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
    
    # Single JOIN query instead of N+1 (was: 2 queries per pedido = 80+ queries for 40 pedidos)
    query = """
        SELECT p.id, p.evento_id, p.usuario_id, p.valor_total, p.valor_frete,
               p.status, p.data_pedido, u.nome_completo, u.setor,
               ip.id as item_id, ip.sabor_id, sp.nome as sabor_nome,
               ip.quantidade, ip.preco_unitario, ip.subtotal
        FROM pedidos p
        JOIN usuarios u ON p.usuario_id = u.id
        LEFT JOIN itens_pedido ip ON ip.pedido_id = p.id
        LEFT JOIN sabores_pizza sp ON ip.sabor_id = sp.id
        WHERE p.evento_id = :evento_id
        ORDER BY p.data_pedido DESC, p.id, ip.id
    """
    
    results = execute_query(query, {"evento_id": evento_id})
    
    # Group rows by pedido_id
    pedidos_map = {}
    for row in results:
        pid = row["ID"]
        if pid not in pedidos_map:
            pedidos_map[pid] = {
                "pedido": row,
                "itens": []
            }
        if row["ITEM_ID"]:
            pedidos_map[pid]["itens"].append(row)
    
    pedidos = []
    for pid, data in pedidos_map.items():
        p = data["pedido"]
        uid = p["USUARIO_ID"]
            
        pedidos.append(PedidoResponse(
            id=p["ID"],
            evento_id=p["EVENTO_ID"],
            usuario_id=uid,
            usuario_nome=p["NOME_COMPLETO"],
            usuario_setor=p["SETOR"],
            is_premium=False,
            valor_total=float(p["VALOR_TOTAL"]),
            valor_frete=float(p["VALOR_FRETE"]),
            status=p["STATUS"],
            data_pedido=p["DATA_PEDIDO"],
            itens=[
                ItemPedidoResponse(
                    id=item["ITEM_ID"],
                    sabor_id=item["SABOR_ID"],
                    sabor_nome=item["SABOR_NOME"],
                    quantidade=item["QUANTIDADE"],
                    preco_unitario=float(item["PRECO_UNITARIO"]),
                    subtotal=float(item["SUBTOTAL"])
                )
                for item in data["itens"]
            ]
        ))
    
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
        SELECT p.id, p.usuario_id, e.status as evento_status
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
    if pedido["USUARIO_ID"] != current_user["id"] and not current_user["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para editar este pedido"
        )
    
    # Verificar se evento ainda está aberto
    if pedido["EVENTO_STATUS"] != 'ABERTO':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível editar pedido de evento que não está mais aberto"
        )
    
    # Atualizar pedido IN-PLACE (preserva data_pedido original!)
    # Buscar preços dos sabores e calcular total (batch - 1 query em vez de N)
    valor_total, itens_validados = _validar_e_precificar_itens(pedido_novo.itens)
    
    valor_frete = 1.00
    
    # Deletar itens antigos e atualizar pedido (sem deletar o pedido!)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Deletar itens antigos
        cursor.execute("DELETE FROM itens_pedido WHERE pedido_id = :pedido_id", {"pedido_id": pedido_id})
        
        # Atualizar valor do pedido (preserva data_pedido e ID original)
        cursor.execute(
            "UPDATE pedidos SET valor_total = :valor_total, valor_frete = :valor_frete WHERE id = :pedido_id",
            {"valor_total": valor_total, "valor_frete": valor_frete, "pedido_id": pedido_id}
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

@router.put("/{pedido_id}/admin-editar", response_model=PedidoResponse)
async def admin_editar_pedido(
    pedido_id: int,
    pedido_novo: PedidoCreate,
    current_user: dict = Depends(get_current_admin_user)
):
    """Permite ADMIN editar qualquer pedido (de qualquer usuário)"""
    
    # Verificar se pedido existe
    check_query = """
        SELECT p.id, p.usuario_id, e.status as evento_status, p.evento_id
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
    
    original_usuario_id = pedido["USUARIO_ID"]
    original_evento_id = pedido["EVENTO_ID"]
    
    # Admin pode editar mesmo se evento estiver FECHADO
    
    # Buscar preços dos sabores e calcular total (batch - 1 query em vez de N)
    valor_total, itens_validados = _validar_e_precificar_itens(pedido_novo.itens)
    
    valor_frete = 1.00
    
    # Deletar itens antigos e atualizar pedido
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Deletar itens antigos
        cursor.execute("DELETE FROM itens_pedido WHERE pedido_id = :pedido_id", {"pedido_id": pedido_id})
        
        # Atualizar valor do pedido
        cursor.execute(
            "UPDATE pedidos SET valor_total = :valor_total, valor_frete = :valor_frete WHERE id = :pedido_id",
            {"valor_total": valor_total, "valor_frete": valor_frete, "pedido_id": pedido_id}
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
    
    # Aviso: admin pode criar em eventos fechados, mas logamos
    evento_status = evento["STATUS"]
    if evento_status != 'ABERTO':
        print(f"[WARN] Admin {current_user['id']} criando pedido em evento {pedido.evento_id} com status {evento_status}")
    
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
    
    # Buscar preços dos sabores e calcular total (batch - 1 query em vez de N)
    valor_total, itens_validados = _validar_e_precificar_itens(pedido.itens)
    
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
        SELECT p.id, p.usuario_id, e.status as evento_status
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
    if pedido["USUARIO_ID"] != current_user["id"] and not current_user["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para cancelar este pedido"
        )
    
    # Verificar se evento ainda está aberto
    if pedido["EVENTO_STATUS"] != 'ABERTO':
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
