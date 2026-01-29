from fastapi import APIRouter, HTTPException, status, Depends
from typing import List, Optional
from datetime import datetime
from models import EventoCreate, EventoUpdate, EventoResponse, ResumoEvento
from auth import get_current_admin_user, get_current_user
from database import execute_query, get_db_connection
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

router = APIRouter(prefix="/eventos", tags=["Eventos"])

# Helper functions
def get_now():
    """
    Retorna a data/hora atual no fuso horário de São Paulo, 
    mas sem info de timezone (naive) para comparar com o banco.
    """
    return datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)

def verificar_e_fechar_eventos_expirados():
    """
    Verifica e fecha automaticamente eventos cuja data_limite já passou.
    Retorna o número de eventos fechados.
    """
    query = """
        UPDATE eventos
        SET status = 'FECHADO'
        WHERE status = 'ABERTO' AND data_limite < :current_time
    """
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, {"current_time": get_now()})
        rows_updated = cursor.rowcount
        conn.commit()
        cursor.close()
    
    return rows_updated

def verificar_evento_aberto_existente(tipo='NORMAL'):
    """
    Verifica se já existe um evento aberto do tipo especificado.
    """
    query = """
        SELECT id, data_evento, status, data_limite, data_criacao, tipo
        FROM eventos
        WHERE status = 'ABERTO' 
        AND data_limite > :current_time
        AND tipo = :tipo
        ORDER BY data_evento ASC
        FETCH FIRST 1 ROWS ONLY
    """
    
    result = execute_query(
        query, 
        {"current_time": get_now(), "tipo": tipo}, 
        fetch_one=True
    )
    
    if result:
        return EventoResponse(
            id=result[0],
            data_evento=result[1],
            status=result[2],
            data_limite=result[3],
            data_criacao=result[4],
            tipo=result[5]
        )
    
    return None


@router.get("/", response_model=List[EventoResponse])
async def listar_eventos(
    current_user: dict = Depends(get_current_user)
):
    """Lista todos os eventos"""
    
    # Incluindo 'tipo' na query
    query = """
        SELECT id, nome, data_evento, status, data_limite, data_criacao, tipo
        FROM eventos
        ORDER BY data_evento DESC
    """
    
    eventos = execute_query(query)
    
    return [
        EventoResponse(
            id=evt["ID"],
            nome=evt.get("NOME"),
            data_evento=evt["DATA_EVENTO"],
            status=evt["STATUS"],
            data_limite=evt["DATA_LIMITE"],
            data_criacao=evt.get("DATA_CRIACAO"),
            tipo=evt.get("TIPO", "NORMAL")
        )
        for evt in eventos
    ]

@router.get("/ativos", response_model=List[EventoResponse])
async def listar_eventos_ativos(
    current_user: dict = Depends(get_current_user)
):
    """Lista todos os eventos ativos (abertos) disponíveis para o usuário"""
    
    # Fechar eventos expirados automaticamente
    verificar_e_fechar_eventos_expirados()
    
    # Buscar eventos abertos
    query = """
        SELECT id, nome, data_evento, status, data_limite, data_criacao, tipo
        FROM eventos
        WHERE status = 'ABERTO' AND data_limite > :current_time
        ORDER BY data_evento ASC
    """
    
    eventos = execute_query(query, {"current_time": get_now()})
    
    return [
        EventoResponse(
            id=evt["ID"],
            nome=evt.get("NOME"),
            data_evento=evt["DATA_EVENTO"],
            status=evt["STATUS"],
            data_limite=evt["DATA_LIMITE"],
            data_criacao=evt.get("DATA_CRIACAO"),
            tipo=evt.get("TIPO", "NORMAL")
        )
        for evt in eventos
    ]

@router.get("/ativo", response_model=EventoResponse)
async def obter_evento_ativo(
    current_user: dict = Depends(get_current_user)
):
    """Obtém o evento atualmente aberto para pedidos"""
    
    # Fechar eventos expirados automaticamente
    verificar_e_fechar_eventos_expirados()
    
    # Query com 'tipo'
    query = """
        SELECT id, data_evento, status, data_limite, data_criacao, tipo
        FROM eventos
        WHERE status = 'ABERTO' 
        AND data_limite > :current_time
        ORDER BY data_evento ASC
        FETCH FIRST 1 ROWS ONLY
    """
    
    result = execute_query(query, {"current_time": get_now()}, fetch_one=True)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Não há evento ativo no momento"
        )
    
    return EventoResponse(
        id=result[0],
        data_evento=result[1],
        status=result[2],
        data_limite=result[3],
        data_criacao=result[4],
        tipo=result[5]
    )

@router.get("/{evento_id}", response_model=EventoResponse)
async def obter_evento(
    evento_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Obtém um evento específico"""
    
    query = """
        SELECT id, data_evento, status, data_limite, data_criacao, tipo
        FROM eventos
        WHERE id = :evento_id
    """
    
    result = execute_query(query, {"evento_id": evento_id}, fetch_one=True)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evento não encontrado"
        )
    
    return EventoResponse(
        id=result[0],
        data_evento=result[1],
        status=result[2],
        data_limite=result[3],
        data_criacao=result[4],
        tipo=result[5]
    )

class EventoCreateRequest(EventoCreate):
    allowed_users: Optional[List[int]] = None

@router.post("/", response_model=EventoResponse, status_code=status.HTTP_201_CREATED)
async def criar_evento(
    evento: EventoCreateRequest,
    current_user: dict = Depends(get_current_admin_user)
):
    """Cria um novo evento (apenas admin)"""
    
    # Verificar se já existe evento aberto DO MESMO TIPO
    evento_existente = verificar_evento_aberto_existente(evento.tipo)
    if evento_existente:
        tipo_str = "Relâmpago" if evento.tipo == 'RELAMPAGO' else "Normal"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Já existe um evento {tipo_str} aberto (Pizzada de {evento_existente.data_evento.strftime('%d/%m/%Y')}). Feche o evento atual antes de criar um novo deste tipo."
        )
    
    # Verificar se já existe evento para esta data
    check_query = "SELECT id FROM eventos WHERE data_evento = :data"
    existing = execute_query(check_query, {"data": evento.data_evento}, fetch_one=True)
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Já existe um evento para esta data"
        )
    
    # Inserir evento COM TIPO
    insert_query = """
        INSERT INTO eventos (nome, data_evento, data_limite, status, tipo)
        VALUES (:nome, :data_evento, :data_limite, 'ABERTO', :tipo)
    """
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            insert_query,
            {
                "nome": evento.nome if evento.nome else None,
                "data_evento": evento.data_evento,
                "data_limite": evento.data_limite,
                "tipo": evento.tipo
            }
        )
        
        # Buscar ID do evento criado
        cursor.execute(
            "SELECT id FROM eventos WHERE data_evento = :data_evento", 
            {"data_evento": evento.data_evento}
        )
        evento_id = cursor.fetchone()[0]
        
        # Se for evento RELAMPAGO e tiver usuários permitidos, salvar acessos
        if evento.tipo == 'RELAMPAGO' and evento.allowed_users:
            insert_acesso = "INSERT INTO evento_acessos (evento_id, usuario_id) VALUES (:evento_id, :usuario_id)"
            for user_id in evento.allowed_users:
                # Verificar se usuário existe para evitar erro de FK
                check_user = "SELECT id FROM usuarios WHERE id = :param_user_id"
                cursor.execute(check_user, {"param_user_id": user_id})
                if cursor.fetchone():
                    cursor.execute(insert_acesso, {"evento_id": evento_id, "usuario_id": user_id})
        
        conn.commit()
        
        # Buscar evento criado
        select_query = """
            SELECT id, nome, data_evento, status, data_limite, data_criacao, tipo
            FROM eventos
            WHERE id = :evento_id
        """
        cursor.execute(select_query, {"evento_id": evento_id})
        result = cursor.fetchone()
        cursor.close()
    
    return EventoResponse(
        id=result[0],
        nome=result[1],
        data_evento=result[2],
        status=result[3],
        data_limite=result[4],
        data_criacao=result[5],
        tipo=result[6]
    )

@router.put("/{evento_id}", response_model=EventoResponse)
async def atualizar_evento(
    evento_id: int,
    evento: EventoUpdate,
    current_user: dict = Depends(get_current_admin_user)
):
    """Atualiza um evento (apenas admin)"""
    
    # Verificar se evento existe e obter seus dados
    check_query = "SELECT id FROM eventos WHERE id = :evento_id"
    existing = execute_query(check_query, {"evento_id": evento_id}, fetch_one=True)
    
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evento não encontrado"
        )
    
    # Construir query de atualização
    updates = []
    params = {"evento_id": evento_id}
    
    if evento.status is not None:
        if evento.status == 'ABERTO':
            # Buscar tipo do evento atual se não foi passado
            tipo_evento = evento.tipo
            if not tipo_evento:
                # Se não passou tipo, usa o do banco
                tipo_query = "SELECT tipo FROM eventos WHERE id = :id"
                tipo_res = execute_query(tipo_query, {"id": evento_id}, fetch_one=True)
                tipo_evento = tipo_res[0] if tipo_res else 'NORMAL'

            evento_existente = verificar_evento_aberto_existente(tipo_evento)
            if evento_existente and evento_existente.id != evento_id:
                tipo_str = "Relâmpago" if tipo_evento == 'RELAMPAGO' else "Normal"
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Não é possível reabrir este evento. Já existe outro evento {tipo_str} aberto (Pizzada de {evento_existente.data_evento.strftime('%d/%m/%Y')})."
                )
        
        updates.append("status = :status")
        params["status"] = evento.status
    
    if evento.nome is not None:
        updates.append("nome = :nome")
        params["nome"] = evento.nome

    if evento.data_limite is not None:
        updates.append("data_limite = :data_limite")
        params["data_limite"] = evento.data_limite

    if evento.tipo is not None:
        updates.append("tipo = :tipo")
        params["tipo"] = evento.tipo
    
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum campo para atualizar"
        )
    
    update_query = f"""
        UPDATE eventos
        SET {', '.join(updates)}
        WHERE id = :evento_id
    """
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(update_query, params)
        conn.commit()
        
        # Buscar evento atualizado
        select_query = """
            SELECT id, data_evento, status, data_limite, data_criacao, tipo
            FROM eventos
            WHERE id = :evento_id
        """
        cursor.execute(select_query, {"evento_id": evento_id})
        result = cursor.fetchone()
        cursor.close()
    
    return EventoResponse(
        id=result[0],
        data_evento=result[1],
        status=result[2],
        data_limite=result[3],
        data_criacao=result[4],
        tipo=result[5]
    )

@router.get("/{evento_id}/resumo", response_model=ResumoEvento)
async def obter_resumo_evento(
    evento_id: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """Obtém resumo completo de um evento (apenas admin)"""
    
    # Buscar dados do evento
    evento_query = """
        SELECT id, data_evento, status, data_limite, data_criacao, tipo
        FROM eventos
        WHERE id = :evento_id
    """
    evento_result = execute_query(evento_query, {"evento_id": evento_id}, fetch_one=True)
    
    if not evento_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evento não encontrado"
        )
    
    # Buscar estatísticas
    stats_query = """
        SELECT 
            COUNT(DISTINCT p.usuario_id) as total_participantes,
            COUNT(p.id) as total_pedidos,
            SUM(p.valor_total + p.valor_frete) as valor_total,
            SUM(ip.quantidade) as total_pedacos
        FROM pedidos p
        LEFT JOIN itens_pedido ip ON p.id = ip.pedido_id
        WHERE p.evento_id = :evento_id
    """
    stats_result = execute_query(stats_query, {"evento_id": evento_id}, fetch_one=True)
    
    total_participantes = int(stats_result[0]) if stats_result[0] else 0
    total_pedidos = int(stats_result[1]) if stats_result[1] else 0
    valor_total = float(stats_result[2]) if stats_result[2] else 0.0
    total_pedacos = int(stats_result[3]) if stats_result[3] else 0
    total_pizzas = total_pedacos // 8
    
    return ResumoEvento(
        evento=EventoResponse(
            id=evento_result[0],
            data_evento=evento_result[1],
            status=evento_result[2],
            data_limite=evento_result[3],
            data_criacao=evento_result[4],
            tipo=evento_result[5]
        ),
        total_participantes=total_participantes,
        total_pedidos=total_pedidos,
        total_pizzas=total_pizzas,
        valor_total=valor_total
    )

@router.delete("/{evento_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deletar_evento(
    evento_id: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """Deleta um evento (apenas admin)"""
    
    # Verificar se há pedidos no evento
    check_pedidos = """
        SELECT COUNT(*) FROM pedidos WHERE evento_id = :evento_id
    """
    result = execute_query(check_pedidos, {"evento_id": evento_id}, fetch_one=True)
    
    if result[0] > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Não é possível deletar evento com {result[0]} pedido(s). Delete os pedidos primeiro."
        )
    
    delete_query = "DELETE FROM eventos WHERE id = :evento_id"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(delete_query, {"evento_id": evento_id})
        
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evento não encontrado"
            )
        
        conn.commit()
        cursor.close()
    
    return None