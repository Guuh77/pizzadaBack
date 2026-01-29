from fastapi import APIRouter, HTTPException, status, Depends
from typing import List
from datetime import datetime
from models import EventoResponse, PedidoResponse
from auth import get_current_user, get_current_admin_user
from database import execute_query
from routes_pedidos import obter_pedido

router = APIRouter(prefix="/pagamentos", tags=["Pagamentos"])

# Constantes
REGRAS_PIZZADA = [
    "AS PIZZAS DEVERÃO CHEGAR ENTRE 12:15 H E 12:45 H, SALVO ALGUM PROBLEMA DA FORNECEDORA",
    "CADA UM DEVE PROVIDENCIAR SUA PRÓPRIA BEBIDA (NADA ALCOÓLICO, POR FAVOR)",
    "SE QUISEREM, PODEM SE UTILIZAR DOS PRATOS PLÁSTICOS REUTILIZÁVEIS (AO FINAL DO EVENTO BASTA LAVAR E DEVOLVER NA PILHA)",
    "TEMOS TAMBÉM TALHERES DESCARTÁVEIS, MAS ACONSELHO TRAZEREM SEUS PRÓPRIOS TALHERES DE METAL",
    "PARA OS QUE PREFERIREM COMER SEM TALHERES, TEMOS ALGUMAS TAMPAS/CAIXAS JÁ CORTADAS PARA AUXILIÁ-LOS",
    "AS PIZZAS FORAM NUMERADAS VISANDO A MELHOR LOCALIZAÇÃO, ENTÃO:",
    "  O NÚMERO AO LADO ESQUERDO DO SEU NOME REFERE-SE AO NÚMERO DA PIZZA (LOCALIZAÇÃO)",
    "  E O NÚMERO DO LADO DIREITO DO SABOR ESCOLHIDO É A QUANTIDADE DE PEDAÇOS QUE FOI SOLICITADO POR VOCÊ",
    "A DISPOSIÇÃO DAS PIZZAS, NO ANDAR (LADO DA STI OU DA SGS), SEGUIU O CRITÉRIO DA QUANTIDADE DE PEDAÇOS DAS PESSOAS DO DEPARTAMENTO.",
    "ASSIM QUE RETIRAR SEU RESPECTIVO PEDAÇO, RISQUE SEU NOME PARA QUE SAIBA MOS QUEM FALTA RETIRAR OS DEMAIS PEDAÇOS.",
    "NÃO EXISTE PEDAÇO SEM DONO, ENTÃO RETIRE APENAS O SEU PEDAÇO. FIQUEI BEM CHATEADO POIS DAS 2 ÚLTIMAS VEZES, SUMIRAM COM PEDAÇOS DE PIZZA, INCLUSIVE O MEU."
]

NOME_RESPONSAVEL = "ROGERIO APARECIDO GOMES ARAUJO SANTOS"
TAXA_ENTREGA = 1.00


def verificar_pagamento_disponivel(evento_id: int) -> bool:
    """
    Verifica se o pagamento está disponível para um evento.
    Disponível quando: status FECHADO/FINALIZADO OU data_limite já passou
    """
    query = """
        SELECT status, data_limite
        FROM eventos
        WHERE id = :evento_id
    """
    
    result = execute_query(query, {"evento_id": evento_id}, fetch_one=True)
    
    if not result:
        return False
    
    status_evento = result[0]
    data_limite = result[1]
    
    # Pagamento disponível se evento fechado/finalizado OU se data limite passou
    if status_evento in ['FECHADO', 'FINALIZADO']:
        return True
    
    if data_limite and data_limite < datetime.now():
        return True
    
    return False


def calcular_numeros_pizza(evento_id: int, usuario_id: int):
    """
    Calcula qual número de pizza cada pedaço do usuário vai cair.
    Retorna um dicionário: {item_pedido_id: [lista de números de pizza]}
    
    IMPORTANTE: Esta função replica EXATAMENTE a lógica do AdminPizzaDashboard.jsx
    - Ordena pedidos por data_pedido (mais antigo primeiro)
    - Agrupa pedaços em pizzas (8 = inteira, 4 = meia)
    - lastUpdate = timestamp do ÚLTIMO slice processado (não o max)
    - STI ordena por lastUpdate DECRESCENTE (mais recente primeiro)
    - SGS ordena por lastUpdate CRESCENTE (mais antigo primeiro)
    - Numera STI primeiro, depois SGS
    - Empates (TIE) não recebem número
    """
    import json
    
    # 1. Buscar todos os pedidos do evento ordenados por data_pedido, id, item_id
    query = """
        SELECT ip.id as item_id, ip.sabor_id, sp.nome as sabor_nome, sp.tipo as sabor_tipo,
               ip.quantidade, p.usuario_id, p.data_pedido, u.setor as usuario_setor
        FROM itens_pedido ip
        JOIN pedidos p ON ip.pedido_id = p.id
        JOIN sabores_pizza sp ON ip.sabor_id = sp.id
        JOIN usuarios u ON p.usuario_id = u.id
        WHERE p.evento_id = :evento_id
        ORDER BY p.data_pedido, p.id, ip.id
    """
    
    todos_itens = execute_query(query, {"evento_id": evento_id})
    
    if not todos_itens:
        return {}
    
    # 2. Buscar configurações salvas
    sector_overrides = {}
    pairing_overrides = {}
    
    config_query = """
        SELECT pairing_overrides, sector_overrides
        FROM pizza_configs
        WHERE evento_id = :evento_id
    """
    
    from database import get_db_connection
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(config_query, {"evento_id": evento_id})
            config_result = cursor.fetchone()
            
            if config_result:
                pairing_val = config_result[0].read() if config_result[0] and hasattr(config_result[0], 'read') else config_result[0]
                sector_val = config_result[1].read() if config_result[1] and hasattr(config_result[1], 'read') else config_result[1]
                
                print(f"[DEBUG] Raw config from DB: pairing_val={pairing_val}, sector_val={sector_val}")
                
                if pairing_val:
                    pairing_overrides = json.loads(pairing_val) if isinstance(pairing_val, str) else {}
                if sector_val:
                    sector_overrides = json.loads(sector_val) if isinstance(sector_val, str) else {}
                
                print(f"[DEBUG] Parsed configs: sector_overrides={sector_overrides}, pairing_overrides={pairing_overrides}")
            else:
                print(f"[DEBUG] Nenhuma config encontrada para evento {evento_id}")
            
            cursor.close()
    except Exception as e:
        print(f"[DEBUG] Erro ao carregar configurações: {e}")
    
    # 3. Converter itens em slices individuais
    # IMPORTANTE: Manter a ordem de processamento igual ao frontend (por data_pedido)
    all_slices = []
    for item in todos_itens:
        for i in range(item["QUANTIDADE"]):
            all_slices.append({
                "item_id": item["ITEM_ID"],
                "flavor_id": item["SABOR_ID"],
                "flavor_name": item["SABOR_NOME"],
                "flavor_type": item["SABOR_TIPO"] or "SALGADA",
                "usuario_id": item["USUARIO_ID"],
                "sector": item["USUARIO_SETOR"] or "",
                "timestamp": item["DATA_PEDIDO"],
            })
    
    # 4. Agrupar slices por sabor (mantendo ordem de inserção)
    slices_by_flavor = {}
    for slice_data in all_slices:
        fid = slice_data["flavor_id"]
        if fid not in slices_by_flavor:
            slices_by_flavor[fid] = {
                "id": fid,
                "name": slice_data["flavor_name"],
                "type": slice_data["flavor_type"],
                "slices": []
            }
        slices_by_flavor[fid]["slices"].append(slice_data)
    
    # 5. Processar grupo de sabores (idêntico ao frontend)
    def process_flavor_group(flavors):
        # Ordenar por popularidade (mais pedaços primeiro), com ID como desempate para garantir ordem determinística
        # IMPORTANTE: Isso garante que frontend e backend gerem os mesmos IDs de pizza
        flavors.sort(key=lambda f: (-len(f["slices"]), f["id"]))
        
        complete_pizzas = []
        half_pizzas = []
        leftovers = []
        
        for flavor in flavors:
            slices = flavor["slices"]
            total = len(slices)
            inteiras = total // 8
            resto = total % 8
            
            # Pizzas inteiras
            for i in range(inteiras):
                pizza_slices = slices[i * 8:(i + 1) * 8]
                # FRONTEND USA: pizzaSlices[pizzaSlices.length - 1].timestamp
                last_update = pizza_slices[-1]["timestamp"]
                complete_pizzas.append({
                    "id": f"{flavor['id']}-inteira-{i}",
                    "flavor_name": flavor["name"],
                    "flavor_type": flavor["type"],
                    "slices_count": 8,
                    "slices": pizza_slices,
                    "is_meio_a_meio": False,
                    "last_update": last_update
                })
            
            # Meias pizzas
            meias = resto // 4
            resto_final = resto % 4
            base_idx = inteiras * 8
            
            for i in range(meias):
                start = base_idx + (i * 4)
                pizza_slices = slices[start:start + 4]
                last_update = pizza_slices[-1]["timestamp"]
                half_pizzas.append({
                    "id": f"{flavor['id']}-meia-{i}",
                    "flavor_id": flavor["id"],
                    "flavor_name": flavor["name"],
                    "flavor_type": flavor["type"],
                    "slices_count": 4,
                    "slices": pizza_slices,
                    "last_update": last_update
                })
            
            # Sobras
            if resto_final > 0:
                start = base_idx + (meias * 4)
                pizza_slices = slices[start:start + resto_final]
                last_update = pizza_slices[-1]["timestamp"]
                leftovers.append({
                    "id": f"{flavor['id']}-resto",
                    "flavor_name": flavor["name"],
                    "flavor_type": flavor["type"],
                    "slices_count": resto_final,
                    "slices": pizza_slices,
                    "is_meio_a_meio": False,
                    "last_update": last_update
                })
        
        return complete_pizzas, half_pizzas, leftovers
    
    # 6. Separar e processar salgados e doces
    all_flavors = list(slices_by_flavor.values())
    salgada_flavors = [f for f in all_flavors if f["type"] != "DOCE"]
    doce_flavors = [f for f in all_flavors if f["type"] == "DOCE"]
    
    salgada_complete, salgada_halves, salgada_leftovers = process_flavor_group(salgada_flavors)
    doce_complete, doce_halves, doce_leftovers = process_flavor_group(doce_flavors)
    
    all_halves = salgada_halves + doce_halves
    
    # 7. Parear meias pizzas
    paired_set = set()
    paired_halves = []
    unpaired_halves = []
    
    # Pareamentos customizados primeiro
    for h1_id, h2_id in pairing_overrides.items():
        h1 = next((h for h in all_halves if h["id"] == h1_id), None)
        h2 = next((h for h in all_halves if h["id"] == h2_id), None)
        if h1 and h2 and h1_id not in paired_set and h2_id not in paired_set:
            combined = h1["slices"] + h2["slices"]
            # Frontend usa: new Date(h1.lastUpdate) > new Date(h2.lastUpdate) ? h1.lastUpdate : h2.lastUpdate
            last_update = max(h1["last_update"], h2["last_update"])
            paired_halves.append({
                "id": f"combined-{h1['id']}-{h2['id']}",
                "flavor_name": f"{h1['flavor_name']} / {h2['flavor_name']}",
                "flavor_type1": h1["flavor_type"],
                "flavor_type2": h2["flavor_type"],
                "half1_id": h1["id"],
                "half2_id": h2["id"],
                "is_meio_a_meio": True,
                "slices_count": 8,
                "slices": combined,
                "last_update": last_update
            })
            paired_set.add(h1_id)
            paired_set.add(h2_id)
    
    # Auto-parear restantes por tipo
    def auto_pair(halves):
        for i in range(0, len(halves), 2):
            if i + 1 < len(halves):
                h1, h2 = halves[i], halves[i + 1]
                combined = h1["slices"] + h2["slices"]
                last_update = max(h1["last_update"], h2["last_update"])
                paired_halves.append({
                    "id": f"combined-{h1['id']}-{h2['id']}",
                    "flavor_name": f"{h1['flavor_name']} / {h2['flavor_name']}",
                    "flavor_type1": h1["flavor_type"],
                    "flavor_type2": h2["flavor_type"],
                    "is_meio_a_meio": True,
                    "slices_count": 8,
                    "slices": combined,
                    "last_update": last_update
                })
            else:
                unpaired_halves.append({**halves[i], "is_meio_a_meio": False})
    
    salgada_unpaired = [h for h in salgada_halves if h["id"] not in paired_set]
    doce_unpaired = [h for h in doce_halves if h["id"] not in paired_set]
    auto_pair(salgada_unpaired)
    auto_pair(doce_unpaired)
    
    # 8. Combinar todas as pizzas (mesma ordem do frontend)
    final_pizzas = (
        salgada_complete + doce_complete +
        paired_halves +
        unpaired_halves +
        salgada_leftovers + doce_leftovers
    )
    
    # 9. Calcular winner (STI/SGS/TIE) e aplicar overrides
    for pizza in final_pizzas:
        sti = sum(1 for s in pizza["slices"] if "STI" in (s.get("sector") or "").upper())
        sgs = sum(1 for s in pizza["slices"] if "SGS" in (s.get("sector") or "").upper())
        
        winner = "TIE"
        if sti > sgs:
            winner = "STI"
        elif sgs > sti:
            winner = "SGS"
        
        # Aplicar override
        if pizza["id"] in sector_overrides:
            winner = sector_overrides[pizza["id"]]
        
        pizza["sti_count"] = sti
        pizza["sgs_count"] = sgs
        pizza["winner"] = winner
        pizza["is_complete"] = pizza["slices_count"] == 8
    
    # 10. Separar e ordenar
    # FRONTEND: stiPizzas sort(b.lastUpdate - a.lastUpdate) = DECRESCENTE
    # FRONTEND: sgsPizzas sort(a.lastUpdate - b.lastUpdate) = CRESCENTE
    sti_pizzas = sorted(
        [p for p in final_pizzas if p["winner"] == "STI"],
        key=lambda p: p["last_update"],
        reverse=True  # Mais recente primeiro
    )
    sgs_pizzas = sorted(
        [p for p in final_pizzas if p["winner"] == "SGS"],
        key=lambda p: p["last_update"]  # Mais antigo primeiro
    )
    
    # 11. Numerar (STI primeiro, depois SGS) - apenas completas
    current_number = 1
    for p in sti_pizzas:
        if p["is_complete"]:
            p["number"] = current_number
            current_number += 1
    for p in sgs_pizzas:
        if p["is_complete"]:
            p["number"] = current_number
            current_number += 1
    
    # DEBUG: Mostrar lista completa de pizzas para comparar com dashboard
    print(f"\n[DEBUG] === LISTA COMPLETA DE PIZZAS (evento {evento_id}) ===")
    print(f"[DEBUG] Total STI completas: {len([p for p in sti_pizzas if p['is_complete']])}")
    print(f"[DEBUG] Total SGS completas: {len([p for p in sgs_pizzas if p['is_complete']])}")
    print(f"[DEBUG] Pizzas STI numeradas:")
    for p in sti_pizzas:
        if p.get("number"):
            print(f"  #{p['number']}: {p['flavor_name']} (STI:{p['sti_count']}, SGS:{p['sgs_count']})")
    print(f"[DEBUG] Pizzas SGS numeradas:")
    for p in sgs_pizzas:
        if p.get("number"):
            print(f"  #{p['number']}: {p['flavor_name']} (STI:{p['sti_count']}, SGS:{p['sgs_count']})")
    print(f"[DEBUG] ===============================================\n")
    
    # 12. Mapear item_id -> números de pizza
    resultado = {}
    for pizza in sti_pizzas + sgs_pizzas:
        num = pizza.get("number")
        if not num:
            continue
        for slice_data in pizza["slices"]:
            if slice_data["usuario_id"] == usuario_id:
                item_id = slice_data["item_id"]
                if item_id not in resultado:
                    resultado[item_id] = []
                resultado[item_id].append(num)
    
    return resultado

@router.get("/meu-historico")
async def obter_meu_historico(
    current_user: dict = Depends(get_current_user)
):
    """
    Retorna o histórico de eventos onde o usuário fez pedidos,
    incluindo informação se o pagamento está disponível
    """
    
    # Buscar eventos onde o usuário tem pedido
    query = """
        SELECT DISTINCT e.id, e.nome, e.data_evento, e.status, e.data_limite, 
               e.data_criacao, e.tipo, p.id as pedido_id
        FROM eventos e
        JOIN pedidos p ON e.id = p.evento_id
        WHERE p.usuario_id = :usuario_id
        ORDER BY e.data_evento DESC
    """
    
    eventos = execute_query(query, {"usuario_id": current_user["id"]})
    
    resultado = []
    for evt in eventos:
        evento_response = EventoResponse(
            id=evt["ID"],
            nome=evt.get("NOME"),
            data_evento=evt["DATA_EVENTO"],
            status=evt["STATUS"],
            data_limite=evt["DATA_LIMITE"],
            data_criacao=evt.get("DATA_CRIACAO"),
            tipo=evt.get("TIPO", "NORMAL")
        )
        
        # Obter pedido
        pedido = await obter_pedido(evt["PEDIDO_ID"], current_user)
        
        # Verificar se pagamento está disponível
        pagamento_disponivel = verificar_pagamento_disponivel(evt["ID"])
        
        resultado.append({
            "evento": evento_response,
            "pedido": pedido,
            "pagamento_disponivel": pagamento_disponivel
        })
    
    return resultado


@router.get("/evento/{evento_id}/disponivel")
async def verificar_disponibilidade_pagamento(
    evento_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Verifica se o pagamento está disponível para um evento específico
    """
    
    # Verificar se usuário tem pedido neste evento
    query = """
        SELECT id FROM pedidos
        WHERE evento_id = :evento_id AND usuario_id = :usuario_id
    """
    
    pedido = execute_query(
        query,
        {"evento_id": evento_id, "usuario_id": current_user["id"]},
        fetch_one=True
    )
    
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Você não tem pedido neste evento"
        )
    
    disponivel = verificar_pagamento_disponivel(evento_id)
    
    return {
        "disponivel": disponivel,
        "mensagem": "Pagamento disponível" if disponivel else "Aguarde o evento ser fechado para efetuar o pagamento"
    }


@router.get("/evento/{evento_id}/relatorio")
async def obter_relatorio_pagamento(
    evento_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Retorna os dados para o relatório de pagamento do usuário
    """
    
    # Verificar se pagamento está disponível
    if not verificar_pagamento_disponivel(evento_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pagamento ainda não disponível. Aguarde o evento ser fechado."
        )
    
    # Buscar evento
    evento_query = """
        SELECT id, nome, data_evento, status, data_limite, data_criacao, tipo
        FROM eventos
        WHERE id = :evento_id
    """
    
    evento_result = execute_query(evento_query, {"evento_id": evento_id}, fetch_one=True)
    
    if not evento_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evento não encontrado"
        )
    
    evento = EventoResponse(
        id=evento_result[0],
        nome=evento_result[1],
        data_evento=evento_result[2],
        status=evento_result[3],
        data_limite=evento_result[4],
        data_criacao=evento_result[5],
        tipo=evento_result[6] if len(evento_result) > 6 else "NORMAL"
    )
    
    # Buscar pedido do usuário
    pedido_query = """
        SELECT id FROM pedidos
        WHERE evento_id = :evento_id AND usuario_id = :usuario_id
    """
    
    pedido_result = execute_query(
        pedido_query,
        {"evento_id": evento_id, "usuario_id": current_user["id"]},
        fetch_one=True
    )
    
    if not pedido_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Você não tem pedido neste evento"
        )
    
    pedido = await obter_pedido(pedido_result[0], current_user)
    
    # Calcular números de pizza para cada item do usuário
    numeros_pizza = calcular_numeros_pizza(evento_id, current_user["id"])
    
    # Adicionar pizza_numeros a cada item do pedido
    pedido_dict = pedido.dict() if hasattr(pedido, 'dict') else pedido.__dict__.copy()
    for item in pedido_dict["itens"]:
        item_id = item["id"]
        item["pizza_numeros"] = numeros_pizza.get(item_id, [])
    
    # Retornar dados para renderização
    return {
        "evento": evento,
        "pedido": pedido_dict,
        "regras": REGRAS_PIZZADA,
        "nome_responsavel": NOME_RESPONSAVEL,
        "taxa_entrega": TAXA_ENTREGA,
        "qr_code_url": "/static/relatorios/qrcode.png",
        "chef_esquerda_url": "/static/relatorios/lado_esquerdo.png",
        "chef_direita_url": "/static/relatorios/lado_direito.png"
    }


@router.put("/evento/{evento_id}/marcar-pago/{pedido_id}")
async def marcar_pedido_como_pago(
    evento_id: int,
    pedido_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Marca um pedido como PAGO (apenas admin)
    """
    
    # Verificar se é admin
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem marcar pedidos como pagos"
        )
    
    # Verificar se pedido existe e pertence ao evento
    query = """
        SELECT id FROM pedidos
        WHERE id = :pedido_id AND evento_id = :evento_id
    """
    
    pedido = execute_query(
        query,
        {"pedido_id": pedido_id, "evento_id": evento_id},
        fetch_one=True
    )
    
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pedido não encontrado"
        )
    
    # Atualizar status para PAGO
    update_query = """
        UPDATE pedidos
        SET status = 'PAGO'
        WHERE id = :pedido_id
    """
    
    execute_query(update_query, {"pedido_id": pedido_id}, commit=True)
    
    return {
        "message": "Pedido marcado como PAGO com sucesso",
        "pedido_id": pedido_id
    }


@router.put("/evento/{evento_id}/informar-pagamento/{pedido_id}")
async def informar_pagamento(
    evento_id: int,
    pedido_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Usuário informa que realizou o pagamento (muda status para AGUARDANDO_CONFIRMACAO)
    """
    
    # Verificar se pedido existe e pertence ao usuário
    query = """
        SELECT id, status FROM pedidos
        WHERE id = :pedido_id AND evento_id = :evento_id AND usuario_id = :usuario_id
    """
    
    pedido = execute_query(
        query,
        {"pedido_id": pedido_id, "evento_id": evento_id, "usuario_id": current_user["id"]},
        fetch_one=True
    )
    
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pedido não encontrado"
        )
    
    # Se já estiver pago, não faz nada
    if pedido[1] == 'PAGO':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este pedido já está pago"
        )

    # Atualizar status para CONFIRMADO (Aguardando Confirmação do Admin)
    update_query = """
        UPDATE pedidos
        SET status = 'CONFIRMADO'
        WHERE id = :pedido_id
    """
    
    execute_query(update_query, {"pedido_id": pedido_id}, commit=True)
    
    return {
        "message": "Pagamento informado com sucesso. Aguarde a confirmação do administrador.",
        "pedido_id": pedido_id,
        "novo_status": "CONFIRMADO"
    }


@router.get("/pendentes")
async def listar_pagamentos_pendentes(
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Lista todos os pedidos com status CONFIRMADO (apenas admin)
    """
    
    query = """
        SELECT p.id, p.evento_id, e.nome as evento_nome, 
               u.nome_completo as usuario_nome, u.setor as usuario_setor,
               p.valor_total, p.valor_frete, p.data_pedido
        FROM pedidos p
        JOIN eventos e ON p.evento_id = e.id
        JOIN usuarios u ON p.usuario_id = u.id
        WHERE p.status = 'CONFIRMADO'
        ORDER BY p.data_pedido DESC
    """
    
    results = execute_query(query)
    
    pagamentos = []
    for row in results:
        pagamentos.append({
            "pedido_id": row["ID"],
            "evento_id": row["EVENTO_ID"],
            "evento_nome": row["EVENTO_NOME"],
            "usuario_nome": row["USUARIO_NOME"],
            "usuario_setor": row["USUARIO_SETOR"],
            "valor_total": float(row["VALOR_TOTAL"]) + float(row["VALOR_FRETE"]),
            "data_pedido": row["DATA_PEDIDO"]
        })
    
    return pagamentos


@router.put("/evento/{evento_id}/desmarcar-pago/{pedido_id}")
async def desmarcar_pedido_como_pago(
    evento_id: int,
    pedido_id: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """
    Desmarca um pedido como PAGO, voltando para PENDENTE (apenas admin)
    """
    
    # Verificar se pedido existe
    query = """
        SELECT id, status FROM pedidos
        WHERE id = :pedido_id AND evento_id = :evento_id
    """
    
    pedido = execute_query(
        query,
        {"pedido_id": pedido_id, "evento_id": evento_id},
        fetch_one=True
    )
    
    if not pedido:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pedido não encontrado"
        )
    
    # Atualizar status para PENDENTE
    update_query = """
        UPDATE pedidos
        SET status = 'PENDENTE'
        WHERE id = :pedido_id
    """
    
    execute_query(update_query, {"pedido_id": pedido_id}, commit=True)
    
    return {
        "message": "Pedido desmarcado como PAGO com sucesso (status: PENDENTE)",
        "pedido_id": pedido_id,
        "novo_status": "PENDENTE"
    }
