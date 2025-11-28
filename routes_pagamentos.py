from fastapi import APIRouter, HTTPException, status, Depends
from typing import List
from datetime import datetime
from models import EventoResponse, PedidoResponse
from auth import get_current_user
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

NOME_RESPONSAVEL = "ROGERIO APARICICIO GOMES ARAUJO SANTOS"
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
    
    # Retornar dados para renderização
    return {
        "evento": evento,
        "pedido": pedido,
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
    
    execute_query(update_query, {"pedido_id": pedido_id})
    
    return {
        "message": "Pedido marcado como PAGO com sucesso",
        "pedido_id": pedido_id
    }
