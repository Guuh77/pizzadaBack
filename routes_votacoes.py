from fastapi import APIRouter, HTTPException, status, Depends
from typing import List
from datetime import datetime, timedelta
from models import (
    VotacaoCreate, VotacaoUpdate, VotacaoResponse, VotacaoResultado,
    VotacaoAdminDetalhe, VotoCreate, EscolhaResponse, EscolhaResultado,
    EscolhaAdminDetalhe, VotanteInfo, MessageResponse
)
from auth import get_current_admin_user, get_current_user
from database import execute_query, get_db_connection

# Timezone handling - Windows compatibility
try:
    from zoneinfo import ZoneInfo
    SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
except Exception:
    # Fallback: Se tzdata não está instalado (Windows), usa offset manual
    SAO_PAULO_TZ = None

router = APIRouter(prefix="/votacoes", tags=["Votações"])

def get_now():
    """Retorna a data/hora atual no fuso horário de São Paulo (naive)."""
    if SAO_PAULO_TZ:
        return datetime.now(SAO_PAULO_TZ).replace(tzinfo=None)
    else:
        # Fallback para Windows: UTC-3 (horário de Brasília padrão)
        return datetime.utcnow() - timedelta(hours=3)


def verificar_e_fechar_votacoes_expiradas():
    """Fecha automaticamente votações cuja data_limite já passou."""
    query = """
        UPDATE votacoes
        SET status = 'FECHADO'
        WHERE status = 'ABERTO' AND data_limite < :current_time
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, {"current_time": get_now()})
        conn.commit()
        cursor.close()


# ============ ADMIN ENDPOINTS ============

@router.post("/", response_model=VotacaoResponse, status_code=status.HTTP_201_CREATED)
async def criar_votacao(
    votacao: VotacaoCreate,
    current_user: dict = Depends(get_current_admin_user)
):
    """Cria uma nova votação (apenas admin)"""
    
    if len(votacao.escolhas) < 2 or len(votacao.escolhas) > 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A votação deve ter entre 2 e 4 escolhas"
        )
    
    if votacao.data_limite <= votacao.data_abertura:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A data limite deve ser posterior à data de abertura"
        )
    
    if votacao.data_resultado_ate < votacao.data_limite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A data de exibição de resultado deve ser igual ou posterior à data limite"
        )
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Inserir votação
        insert_votacao = """
            INSERT INTO votacoes (titulo, data_abertura, data_limite, data_resultado_ate, status, criado_por)
            VALUES (:titulo, :data_abertura, :data_limite, :data_resultado_ate, 'ABERTO', :criado_por)
        """
        cursor.execute(insert_votacao, {
            "titulo": votacao.titulo,
            "data_abertura": votacao.data_abertura,
            "data_limite": votacao.data_limite,
            "data_resultado_ate": votacao.data_resultado_ate,
            "criado_por": current_user["id"]
        })
        
        # Buscar ID da votação criada
        cursor.execute("SELECT MAX(id) FROM votacoes WHERE criado_por = :user_id", {"user_id": current_user["id"]})
        votacao_id = cursor.fetchone()[0]
        
        # Inserir escolhas
        insert_escolha = """
            INSERT INTO votacao_escolhas (votacao_id, texto, ordem)
            VALUES (:votacao_id, :texto, :ordem)
        """
        for i, escolha in enumerate(votacao.escolhas):
            cursor.execute(insert_escolha, {
                "votacao_id": votacao_id,
                "texto": escolha.texto,
                "ordem": i + 1
            })
        
        conn.commit()
        
        # Buscar votação completa
        cursor.execute("""
            SELECT id, titulo, data_abertura, data_limite, data_resultado_ate, status, criado_por, data_criacao
            FROM votacoes WHERE id = :id
        """, {"id": votacao_id})
        row = cursor.fetchone()
        
        cursor.execute("""
            SELECT id, texto, ordem FROM votacao_escolhas WHERE votacao_id = :id ORDER BY ordem
        """, {"id": votacao_id})
        escolhas = cursor.fetchall()
        cursor.close()
    
    return VotacaoResponse(
        id=row[0],
        titulo=row[1],
        data_abertura=row[2],
        data_limite=row[3],
        data_resultado_ate=row[4],
        status=row[5],
        criado_por=row[6],
        data_criacao=row[7],
        escolhas=[EscolhaResponse(id=e[0], texto=e[1], ordem=e[2]) for e in escolhas]
    )


@router.get("/", response_model=List[VotacaoResponse])
async def listar_todas_votacoes(
    current_user: dict = Depends(get_current_admin_user)
):
    """Lista todas as votações - histórico completo (apenas admin)"""
    verificar_e_fechar_votacoes_expiradas()
    
    query = """
        SELECT id, titulo, data_abertura, data_limite, data_resultado_ate, status, criado_por, data_criacao
        FROM votacoes ORDER BY data_criacao DESC
    """
    votacoes = execute_query(query)
    
    result = []
    for v in votacoes:
        escolhas_query = "SELECT id, texto, ordem FROM votacao_escolhas WHERE votacao_id = :id ORDER BY ordem"
        escolhas = execute_query(escolhas_query, {"id": v["ID"]})
        
        result.append(VotacaoResponse(
            id=v["ID"],
            titulo=v["TITULO"],
            data_abertura=v["DATA_ABERTURA"],
            data_limite=v["DATA_LIMITE"],
            data_resultado_ate=v["DATA_RESULTADO_ATE"],
            status=v["STATUS"],
            criado_por=v["CRIADO_POR"],
            data_criacao=v.get("DATA_CRIACAO"),
            escolhas=[EscolhaResponse(id=e["ID"], texto=e["TEXTO"], ordem=e["ORDEM"]) for e in escolhas]
        ))
    
    return result


@router.get("/{votacao_id}/detalhes", response_model=VotacaoAdminDetalhe)
async def obter_detalhes_votacao(
    votacao_id: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """Obtém detalhes completos da votação incluindo quem votou em quê (apenas admin)"""
    
    query = """
        SELECT id, titulo, data_abertura, data_limite, data_resultado_ate, status, criado_por, data_criacao
        FROM votacoes WHERE id = :id
    """
    votacao = execute_query(query, {"id": votacao_id}, fetch_one=True)
    
    if not votacao:
        raise HTTPException(status_code=404, detail="Votação não encontrada")
    
    # Buscar escolhas com votos e votantes
    escolhas_query = "SELECT id, texto, ordem FROM votacao_escolhas WHERE votacao_id = :id ORDER BY ordem"
    escolhas = execute_query(escolhas_query, {"id": votacao_id})
    
    escolhas_detalhe = []
    total_votos = 0
    
    for e in escolhas:
        # Buscar votantes desta escolha
        votantes_query = """
            SELECT v.usuario_id, u.nome_completo, u.setor, v.data_voto
            FROM votos v
            JOIN usuarios u ON v.usuario_id = u.id
            WHERE v.escolha_id = :escolha_id
            ORDER BY v.data_voto
        """
        votantes = execute_query(votantes_query, {"escolha_id": e["ID"]})
        
        votos_count = len(votantes)
        total_votos += votos_count
        
        escolhas_detalhe.append(EscolhaAdminDetalhe(
            id=e["ID"],
            texto=e["TEXTO"],
            ordem=e["ORDEM"],
            votos=votos_count,
            votantes=[
                VotanteInfo(
                    usuario_id=vt["USUARIO_ID"],
                    nome=vt["NOME_COMPLETO"],
                    setor=vt["SETOR"],
                    data_voto=vt.get("DATA_VOTO")
                ) for vt in votantes
            ]
        ))
    
    return VotacaoAdminDetalhe(
        id=votacao[0],
        titulo=votacao[1],
        data_abertura=votacao[2],
        data_limite=votacao[3],
        data_resultado_ate=votacao[4],
        status=votacao[5],
        criado_por=votacao[6],
        data_criacao=votacao[7],
        total_votos=total_votos,
        escolhas=escolhas_detalhe
    )


@router.put("/{votacao_id}", response_model=VotacaoResponse)
async def atualizar_votacao(
    votacao_id: int,
    votacao: VotacaoUpdate,
    current_user: dict = Depends(get_current_admin_user)
):
    """Atualiza uma votação - datas, status (apenas admin)"""
    
    check_query = "SELECT id FROM votacoes WHERE id = :id"
    existing = execute_query(check_query, {"id": votacao_id}, fetch_one=True)
    
    if not existing:
        raise HTTPException(status_code=404, detail="Votação não encontrada")
    
    updates = []
    params = {"id": votacao_id}
    
    if votacao.titulo is not None:
        updates.append("titulo = :titulo")
        params["titulo"] = votacao.titulo
    
    if votacao.data_limite is not None:
        updates.append("data_limite = :data_limite")
        params["data_limite"] = votacao.data_limite
    
    if votacao.data_resultado_ate is not None:
        updates.append("data_resultado_ate = :data_resultado_ate")
        params["data_resultado_ate"] = votacao.data_resultado_ate
    
    if votacao.status is not None:
        updates.append("status = :status")
        params["status"] = votacao.status
    
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    
    update_query = f"UPDATE votacoes SET {', '.join(updates)} WHERE id = :id"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(update_query, params)
        conn.commit()
        
        cursor.execute("""
            SELECT id, titulo, data_abertura, data_limite, data_resultado_ate, status, criado_por, data_criacao
            FROM votacoes WHERE id = :id
        """, {"id": votacao_id})
        row = cursor.fetchone()
        
        cursor.execute("SELECT id, texto, ordem FROM votacao_escolhas WHERE votacao_id = :id ORDER BY ordem", {"id": votacao_id})
        escolhas = cursor.fetchall()
        cursor.close()
    
    return VotacaoResponse(
        id=row[0],
        titulo=row[1],
        data_abertura=row[2],
        data_limite=row[3],
        data_resultado_ate=row[4],
        status=row[5],
        criado_por=row[6],
        data_criacao=row[7],
        escolhas=[EscolhaResponse(id=e[0], texto=e[1], ordem=e[2]) for e in escolhas]
    )


@router.delete("/{votacao_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deletar_votacao(
    votacao_id: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """Deleta uma votação (apenas admin)"""
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM votacoes WHERE id = :id", {"id": votacao_id})
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Votação não encontrada")
        
        conn.commit()
        cursor.close()
    
    return None


# ============ USER ENDPOINTS ============

@router.get("/ativas", response_model=List[VotacaoResultado])
async def listar_votacoes_ativas(
    current_user: dict = Depends(get_current_user)
):
    """Lista votações abertas para votação (usuário comum) - inclui status de voto"""
    verificar_e_fechar_votacoes_expiradas()
    now = get_now()
    user_id = current_user["id"]
    
    query = """
        SELECT id, titulo, data_abertura, data_limite, data_resultado_ate, status, criado_por, data_criacao
        FROM votacoes 
        WHERE status = 'ABERTO' 
        AND data_abertura <= :now 
        AND data_limite > :now
        ORDER BY data_criacao DESC
    """
    votacoes = execute_query(query, {"now": now})
    
    result = []
    for v in votacoes:
        votacao_dict = {
            "ID": v["ID"],
            "TITULO": v["TITULO"],
            "DATA_ABERTURA": v["DATA_ABERTURA"],
            "DATA_LIMITE": v["DATA_LIMITE"],
            "DATA_RESULTADO_ATE": v["DATA_RESULTADO_ATE"],
            "STATUS": v["STATUS"],
            "CRIADO_POR": v["CRIADO_POR"],
            "DATA_CRIACAO": v.get("DATA_CRIACAO")
        }
        votacao_result = _build_votacao_resultado(votacao_dict, user_id, force_show=True)
        if votacao_result:
            result.append(votacao_result)
    
    return result


@router.get("/resultados-visiveis", response_model=List[VotacaoResultado])
async def listar_resultados_visiveis(
    current_user: dict = Depends(get_current_user)
):
    """Lista votações encerradas cujos resultados ainda estão visíveis"""
    verificar_e_fechar_votacoes_expiradas()
    now = get_now()
    user_id = current_user["id"]
    
    query = """
        SELECT id, titulo, data_abertura, data_limite, data_resultado_ate, status, criado_por, data_criacao
        FROM votacoes 
        WHERE (status = 'FECHADO' OR status = 'FINALIZADO')
        AND data_resultado_ate >= :now
        ORDER BY data_criacao DESC
    """
    votacoes = execute_query(query, {"now": now})
    
    result = []
    for v in votacoes:
        votacao_result = _build_votacao_resultado(v, user_id)
        if votacao_result:
            result.append(votacao_result)
    
    return result


@router.get("/{votacao_id}", response_model=VotacaoResultado)
async def obter_votacao(
    votacao_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Obtém uma votação com resultados (se usuário já votou ou votação encerrada)"""
    verificar_e_fechar_votacoes_expiradas()
    user_id = current_user["id"]
    
    query = """
        SELECT id, titulo, data_abertura, data_limite, data_resultado_ate, status, criado_por, data_criacao
        FROM votacoes WHERE id = :id
    """
    votacao = execute_query(query, {"id": votacao_id}, fetch_one=True)
    
    if not votacao:
        raise HTTPException(status_code=404, detail="Votação não encontrada")
    
    votacao_dict = {
        "ID": votacao[0],
        "TITULO": votacao[1],
        "DATA_ABERTURA": votacao[2],
        "DATA_LIMITE": votacao[3],
        "DATA_RESULTADO_ATE": votacao[4],
        "STATUS": votacao[5],
        "CRIADO_POR": votacao[6],
        "DATA_CRIACAO": votacao[7]
    }
    
    result = _build_votacao_resultado(votacao_dict, user_id)
    if not result:
        raise HTTPException(status_code=403, detail="Você não tem permissão para ver os resultados desta votação")
    
    return result


@router.post("/{votacao_id}/votar", response_model=VotacaoResultado)
async def votar(
    votacao_id: int,
    voto: VotoCreate,
    current_user: dict = Depends(get_current_user)
):
    """Registra o voto do usuário"""
    verificar_e_fechar_votacoes_expiradas()
    now = get_now()
    user_id = current_user["id"]
    
    # Verificar se votação está aberta
    votacao_query = """
        SELECT id, status, data_abertura, data_limite FROM votacoes WHERE id = :id
    """
    votacao = execute_query(votacao_query, {"id": votacao_id}, fetch_one=True)
    
    if not votacao:
        raise HTTPException(status_code=404, detail="Votação não encontrada")
    
    if votacao[1] != 'ABERTO':
        raise HTTPException(status_code=400, detail="Esta votação não está aberta")
    
    if now < votacao[2]:
        raise HTTPException(status_code=400, detail="Esta votação ainda não começou")
    
    if now > votacao[3]:
        raise HTTPException(status_code=400, detail="Esta votação já encerrou")
    
    # Verificar se escolha pertence a esta votação
    escolha_query = "SELECT id FROM votacao_escolhas WHERE id = :escolha_id AND votacao_id = :votacao_id"
    escolha = execute_query(escolha_query, {"escolha_id": voto.escolha_id, "votacao_id": votacao_id}, fetch_one=True)
    
    if not escolha:
        raise HTTPException(status_code=400, detail="Escolha inválida para esta votação")
    
    # Verificar se usuário já votou
    voto_existente_query = """
        SELECT v.id FROM votos v
        JOIN votacao_escolhas e ON v.escolha_id = e.id
        WHERE e.votacao_id = :votacao_id AND v.usuario_id = :user_id
    """
    voto_existente = execute_query(voto_existente_query, {"votacao_id": votacao_id, "user_id": user_id}, fetch_one=True)
    
    if voto_existente:
        # Atualizar voto existente (usuário está alterando seu voto)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE votos SET escolha_id = :escolha_id, data_voto = CURRENT_TIMESTAMP WHERE id = :voto_id",
                {"escolha_id": voto.escolha_id, "voto_id": voto_existente[0]}
            )
            conn.commit()
            cursor.close()
    else:
        # Registrar novo voto
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO votos (escolha_id, usuario_id) VALUES (:escolha_id, :user_id)",
                {"escolha_id": voto.escolha_id, "user_id": user_id}
            )
            conn.commit()
            cursor.close()
    
    # Retornar resultado completo
    votacao_full = execute_query("""
        SELECT id, titulo, data_abertura, data_limite, data_resultado_ate, status, criado_por, data_criacao
        FROM votacoes WHERE id = :id
    """, {"id": votacao_id}, fetch_one=True)
    
    votacao_dict = {
        "ID": votacao_full[0],
        "TITULO": votacao_full[1],
        "DATA_ABERTURA": votacao_full[2],
        "DATA_LIMITE": votacao_full[3],
        "DATA_RESULTADO_ATE": votacao_full[4],
        "STATUS": votacao_full[5],
        "CRIADO_POR": votacao_full[6],
        "DATA_CRIACAO": votacao_full[7]
    }
    
    return _build_votacao_resultado(votacao_dict, user_id, force_show=True)


def _build_votacao_resultado(votacao_dict: dict, user_id: int, force_show: bool = False) -> VotacaoResultado:
    """Helper para construir VotacaoResultado com porcentagens"""
    votacao_id = votacao_dict["ID"]
    
    # Verificar se usuário já votou
    voto_usuario_query = """
        SELECT e.id FROM votos v
        JOIN votacao_escolhas e ON v.escolha_id = e.id
        WHERE e.votacao_id = :votacao_id AND v.usuario_id = :user_id
    """
    voto_usuario = execute_query(voto_usuario_query, {"votacao_id": votacao_id, "user_id": user_id}, fetch_one=True)
    usuario_votou = voto_usuario is not None
    escolha_usuario = voto_usuario[0] if voto_usuario else None
    
    # Se não votou e votação ainda aberta e não force_show, não pode ver resultados
    now = get_now()
    votacao_aberta = votacao_dict["STATUS"] == 'ABERTO' and now <= votacao_dict["DATA_LIMITE"]
    
    if not usuario_votou and votacao_aberta and not force_show:
        return None
    
    # Buscar escolhas com contagem de votos
    escolhas_query = """
        SELECT e.id, e.texto, e.ordem, COUNT(v.id) as votos
        FROM votacao_escolhas e
        LEFT JOIN votos v ON e.id = v.escolha_id
        WHERE e.votacao_id = :votacao_id
        GROUP BY e.id, e.texto, e.ordem
        ORDER BY e.ordem
    """
    escolhas = execute_query(escolhas_query, {"votacao_id": votacao_id})
    
    total_votos = sum(e["VOTOS"] for e in escolhas)
    
    escolhas_resultado = []
    for e in escolhas:
        votos = e["VOTOS"]
        porcentagem = (votos / total_votos * 100) if total_votos > 0 else 0
        escolhas_resultado.append(EscolhaResultado(
            id=e["ID"],
            texto=e["TEXTO"],
            ordem=e["ORDEM"],
            votos=votos,
            porcentagem=round(porcentagem, 1)
        ))
    
    return VotacaoResultado(
        id=votacao_dict["ID"],
        titulo=votacao_dict["TITULO"],
        data_abertura=votacao_dict["DATA_ABERTURA"],
        data_limite=votacao_dict["DATA_LIMITE"],
        data_resultado_ate=votacao_dict["DATA_RESULTADO_ATE"],
        status=votacao_dict["STATUS"],
        total_votos=total_votos,
        escolhas=escolhas_resultado,
        usuario_votou=usuario_votou,
        escolha_usuario=escolha_usuario
    )
