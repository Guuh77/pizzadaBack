from fastapi import APIRouter, HTTPException, status, Depends
from models import DashboardResponse, EstatisticasPizza
from auth import get_current_user
from database import execute_query

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/evento/{evento_id}", response_model=DashboardResponse)
async def obter_dashboard_evento(
    evento_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Obtém dashboard completo do evento com estatísticas em tempo real
    Mostra agrupamento inteligente de pizzas
    """
    
    # Verificar se evento existe
    evento_query = """
        SELECT id, data_evento, status
        FROM eventos
        WHERE id = :evento_id
    """
    evento = execute_query(evento_query, {"evento_id": evento_id}, fetch_one=True)
    
    if not evento:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evento não encontrado"
        )
    
    # Buscar estatísticas gerais
    stats_query = """
        SELECT 
            COUNT(DISTINCT p.usuario_id) as total_participantes,
            COUNT(p.id) as total_pedidos,
            SUM(p.valor_total + p.valor_frete) as valor_total
        FROM pedidos p
        WHERE p.evento_id = :evento_id
    """
    stats = execute_query(stats_query, {"evento_id": evento_id}, fetch_one=True)
    
    total_participantes = int(stats[0]) if stats[0] else 0
    total_pedidos = int(stats[1]) if stats[1] else 0
    valor_total = float(stats[2]) if stats[2] else 0.0
    
    # Buscar estatísticas por sabor APENAS DESTE EVENTO (agrupamento inteligente)
    sabores_query = """
        SELECT 
            sp.id as sabor_id,
            sp.nome as sabor_nome,
            COALESCE(SUM(ip.quantidade), 0) as total_pedacos,
            sp.preco_pedaco
        FROM sabores_pizza sp
        INNER JOIN itens_pedido ip ON sp.id = ip.sabor_id
        INNER JOIN pedidos p ON ip.pedido_id = p.id
        WHERE sp.ativo = 1
        AND p.evento_id = :evento_id
        GROUP BY sp.id, sp.nome, sp.preco_pedaco
        HAVING COALESCE(SUM(ip.quantidade), 0) > 0
        ORDER BY total_pedacos DESC, sp.nome
    """
    
    sabores_results = execute_query(sabores_query, {"evento_id": evento_id})
    
    estatisticas_sabores = []
    for sabor in sabores_results:
        total_pedacos = int(sabor["TOTAL_PEDACOS"])
        pizzas_completas = total_pedacos // 8  # Cada pizza tem 8 pedaços
        pedacos_restantes = total_pedacos % 8
        preco_pedaco = float(sabor["PRECO_PEDACO"])
        valor_total_sabor = total_pedacos * preco_pedaco
        
        estatisticas_sabores.append(
            EstatisticasPizza(
                sabor_id=sabor["SABOR_ID"],
                sabor_nome=sabor["SABOR_NOME"],
                total_pedacos=total_pedacos,
                pizzas_completas=pizzas_completas,
                pedacos_restantes=pedacos_restantes,
                valor_total=valor_total_sabor
            )
        )
    
    return DashboardResponse(
        evento_id=evento[0],
        data_evento=evento[1],
        status=evento[2],
        total_participantes=total_participantes,
        total_pedidos=total_pedidos,
        valor_total_evento=valor_total,
        estatisticas_por_sabor=estatisticas_sabores
    )

@router.get("/evento/{evento_id}/oportunidades")
async def obter_oportunidades(
    evento_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Retorna oportunidades para completar pizzas
    Mostra sabores que estão próximos de fechar pizzas inteiras ou meias
    """
    
    # Buscar estatísticas por sabor APENAS DESTE EVENTO
    sabores_query = """
        SELECT 
            sp.id as sabor_id,
            sp.nome as sabor_nome,
            COALESCE(SUM(ip.quantidade), 0) as total_pedacos,
            sp.preco_pedaco
        FROM sabores_pizza sp
        INNER JOIN itens_pedido ip ON sp.id = ip.sabor_id
        INNER JOIN pedidos p ON ip.pedido_id = p.id
        WHERE sp.ativo = 1
        AND p.evento_id = :evento_id
        GROUP BY sp.id, sp.nome, sp.preco_pedaco
        HAVING COALESCE(SUM(ip.quantidade), 0) > 0
        ORDER BY total_pedacos DESC
    """
    
    sabores_results = execute_query(sabores_query, {"evento_id": evento_id})
    
    oportunidades = []
    
    for sabor in sabores_results:
        total_pedacos = int(sabor["TOTAL_PEDACOS"])
        pedacos_restantes = total_pedacos % 8
        
        # CORRIGIDO: Ignorar meias completas (4 pedaços), pois elas devem ser combinadas em meio-a-meio
        # Só mostra PEDAÇOS AVULSOS que realmente precisam completar (1-3 ou 5-7 pedaços)
        if pedacos_restantes > 0 and pedacos_restantes != 4:
            pedacos_para_completar = 8 - pedacos_restantes
            
            # Considerar oportunidade apenas se faltar 4 ou menos pedaços
            # (pedaços_restantes 5, 6, 7 - faltam 3, 2, 1)
            if pedacos_para_completar <= 4:
                oportunidades.append({
                    "sabor_id": sabor["SABOR_ID"],
                    "sabor_nome": sabor["SABOR_NOME"],
                    "total_pedacos_atual": total_pedacos,
                    "pedacos_para_completar": pedacos_para_completar,
                    "preco_por_pedaco": float(sabor["PRECO_PEDACO"]),
                    "valor_para_completar": pedacos_para_completar * float(sabor["PRECO_PEDACO"]),
                    "tipo": "inteira"  # Sempre "inteira" agora, pois meias já estão sendo combinadas
                })
    
    # Ordenar por quantidade de pedaços necessários (menos pedaços primeiro)
    oportunidades.sort(key=lambda x: x["pedacos_para_completar"])
    
    return {
        "evento_id": evento_id,
        "total_oportunidades": len(oportunidades),
        "oportunidades": oportunidades,
        "mensagem": "Aproveite para completar essas pizzas!" if oportunidades else "Todas as pizzas estão completas! 🎉"
    }

@router.get("/evento/{evento_id}/agrupamento-inteligente")
async def agrupar_pizzas_inteligente(
    evento_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Agrupa pizzas de forma inteligente:
    - 8 pedaços = 1 pizza inteira
    - 4 pedaços = meia pizza (combina com outra meia)
    - Resto = pedaços avulsos esperando completar
    """
    
    # Buscar todos os sabores com pedidos APENAS DESTE EVENTO
    # Buscar todos os sabores com pedidos APENAS DESTE EVENTO
    query = """
        SELECT 
            sp.id as sabor_id,
            sp.nome as sabor_nome,
            sp.tipo as sabor_tipo,
            COALESCE(SUM(ip.quantidade), 0) as total_pedacos
        FROM sabores_pizza sp
        INNER JOIN itens_pedido ip ON sp.id = ip.sabor_id
        INNER JOIN pedidos p ON ip.pedido_id = p.id
        WHERE sp.ativo = 1
        AND p.evento_id = :evento_id
        GROUP BY sp.id, sp.nome, sp.tipo
        HAVING COALESCE(SUM(ip.quantidade), 0) > 0
        ORDER BY total_pedacos DESC
    """
    
    sabores_results = execute_query(query, {"evento_id": evento_id})
    
    def processar_lista_sabores(lista_sabores):
        pizzas_inteiras = []
        meias_pizzas = []
        pedacos_avulsos = []
        
        for sabor in lista_sabores:
            total = int(sabor["TOTAL_PEDACOS"])
            nome = sabor["SABOR_NOME"]
            
            # Calcular inteiras
            inteiras = total // 8
            resto = total % 8
            
            if inteiras > 0:
                pizzas_inteiras.append({
                    "tipo": "inteira",
                    "sabor": nome,
                    "quantidade": inteiras,
                    "pedacos": inteiras * 8
                })
            
            # Calcular meias
            meias = resto // 4
            resto_final = resto % 4
            
            if meias > 0:
                for _ in range(meias):
                    meias_pizzas.append({
                        "sabor": nome,
                        "pedacos": 4
                    })
            
            if resto_final > 0:
                pedacos_avulsos.append({
                    "sabor": nome,
                    "pedacos": resto_final,
                    "faltam": 4 - resto_final
                })
        
        # Combinar meias pizzas
        pizzas_meio_a_meio = []
        i = 0
        while i < len(meias_pizzas) - 1:
            pizzas_meio_a_meio.append({
                "tipo": "meio_a_meio",
                "sabor1": meias_pizzas[i]["sabor"],
                "sabor2": meias_pizzas[i+1]["sabor"],
                "pedacos": 8
            })
            i += 2
        
        # Se sobrou uma meia sozinha
        if len(meias_pizzas) % 2 == 1:
            pedacos_avulsos.append({
                "sabor": meias_pizzas[-1]["sabor"],
                "pedacos": 4,
                "faltam": 4,
                "tipo": "meia_esperando"
            })
            
        return pizzas_inteiras, pizzas_meio_a_meio, pedacos_avulsos

    # Separar sabores por tipo
    sabores_salgados = [s for s in sabores_results if s.get("SABOR_TIPO", "SALGADA") != "DOCE"]
    sabores_doces = [s for s in sabores_results if s.get("SABOR_TIPO") == "DOCE"]
    
    # Processar cada grupo separadamente
    inteiras_salg, meio_salg, avulsos_salg = processar_lista_sabores(sabores_salgados)
    inteiras_doces, meio_doces, avulsos_doces = processar_lista_sabores(sabores_doces)
    
    # Combinar resultados
    pizzas_inteiras = inteiras_salg + inteiras_doces
    pizzas_meio_a_meio = meio_salg + meio_doces
    pedacos_avulsos = avulsos_salg + avulsos_doces
    
    total_pizzas_completas = len(pizzas_inteiras) + len(pizzas_meio_a_meio)
    
    return {
        "evento_id": evento_id,
        "total_pizzas_completas": total_pizzas_completas,
        "pizzas_inteiras": pizzas_inteiras,
        "pizzas_meio_a_meio": pizzas_meio_a_meio,
        "pedacos_avulsos": pedacos_avulsos,
        "resumo": f"{total_pizzas_completas} pizzas completas prontas para pedir!"
    }
