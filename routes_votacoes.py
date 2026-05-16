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
        
        # Buscar ID da votação criada (order by data_criacao DESC para evitar race condition)
        cursor.execute("""
            SELECT id FROM votacoes WHERE criado_por = :user_id ORDER BY data_criacao DESC FETCH FIRST 1 ROWS ONLY
        """, {"user_id": current_user["id"]})
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
    
    # Single JOIN query instead of N+1
    query = """
        SELECT v.id, v.titulo, v.data_abertura, v.data_limite, v.data_resultado_ate, 
               v.status, v.criado_por, v.data_criacao,
               e.id as escolha_id, e.texto, e.ordem
        FROM votacoes v
        LEFT JOIN votacao_escolhas e ON e.votacao_id = v.id
        ORDER BY v.data_criacao DESC, e.ordem
    """
    rows = execute_query(query)
    
    votacoes_map = {}
    for row in rows:
        vid = row["ID"]
        if vid not in votacoes_map:
            votacoes_map[vid] = {"votacao": row, "escolhas": []}
        if row["ESCOLHA_ID"]:
            votacoes_map[vid]["escolhas"].append(row)
    
    result = []
    for vid, data in votacoes_map.items():
        v = data["votacao"]
        result.append(VotacaoResponse(
            id=v["ID"],
            titulo=v["TITULO"],
            data_abertura=v["DATA_ABERTURA"],
            data_limite=v["DATA_LIMITE"],
            data_resultado_ate=v["DATA_RESULTADO_ATE"],
            status=v["STATUS"],
            criado_por=v["CRIADO_POR"],
            data_criacao=v.get("DATA_CRIACAO"),
            escolhas=[EscolhaResponse(id=e["ESCOLHA_ID"], texto=e["TEXTO"], ordem=e["ORDEM"]) for e in data["escolhas"]]
        ))
    
    return result


@router.get("/{votacao_id}/detalhes", response_model=VotacaoAdminDetalhe)
async def obter_detalhes_votacao(
    votacao_id: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """Obtém detalhes completos da votação incluindo quem votou em quê (apenas admin)"""
    
    # Single query for votacao + escolhas + votantes
    query = """
        SELECT v.id, v.titulo, v.data_abertura, v.data_limite, v.data_resultado_ate, 
               v.status, v.criado_por, v.data_criacao,
               e.id as escolha_id, e.texto, e.ordem,
               vt.usuario_id, u.nome_completo, u.setor, vt.data_voto
        FROM votacoes v
        LEFT JOIN votacao_escolhas e ON e.votacao_id = v.id
        LEFT JOIN votos vt ON vt.escolha_id = e.id
        LEFT JOIN usuarios u ON vt.usuario_id = u.id
        WHERE v.id = :id
        ORDER BY e.ordem, vt.data_voto
    """
    rows = execute_query(query, {"id": votacao_id})
    
    if not rows:
        raise HTTPException(status_code=404, detail="Votação não encontrada")
    
    votacao = rows[0]
    
    # Group by escolha
    escolhas_map = {}
    total_votos = 0
    for row in rows:
        eid = row["ESCOLHA_ID"]
        if not eid:
            continue
        if eid not in escolhas_map:
            escolhas_map[eid] = {"escolha": row, "votantes": []}
        if row["USUARIO_ID"]:
            escolhas_map[eid]["votantes"].append(row)
            total_votos += 1
    
    escolhas_detalhe = []
    for eid, data in escolhas_map.items():
        e = data["escolha"]
        escolhas_detalhe.append(EscolhaAdminDetalhe(
            id=e["ESCOLHA_ID"],
            texto=e["TEXTO"],
            ordem=e["ORDEM"],
            votos=len(data["votantes"]),
            votantes=[
                VotanteInfo(
                    usuario_id=vt["USUARIO_ID"],
                    nome=vt["NOME_COMPLETO"],
                    setor=vt["SETOR"],
                    data_voto=vt.get("DATA_VOTO")
                ) for vt in data["votantes"]
            ]
        ))
    
    return VotacaoAdminDetalhe(
        id=votacao["ID"],
        titulo=votacao["TITULO"],
        data_abertura=votacao["DATA_ABERTURA"],
        data_limite=votacao["DATA_LIMITE"],
        data_resultado_ate=votacao["DATA_RESULTADO_ATE"],
        status=votacao["STATUS"],
        criado_por=votacao["CRIADO_POR"],
        data_criacao=votacao.get("DATA_CRIACAO"),
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
    
    # Single JOIN query: votacoes + escolhas + vote counts + user vote
    query = """
        SELECT v.id, v.titulo, v.data_abertura, v.data_limite, v.data_resultado_ate, 
               v.status, v.criado_por, v.data_criacao,
               e.id as escolha_id, e.texto, e.ordem,
               COUNT(vt.id) as votos,
               MAX(CASE WHEN vt.usuario_id = :user_id THEN e.id END) as user_escolha_id
        FROM votacoes v
        LEFT JOIN votacao_escolhas e ON e.votacao_id = v.id
        LEFT JOIN votos vt ON vt.escolha_id = e.id
        WHERE v.status = 'ABERTO' 
        AND v.data_abertura <= :now 
        AND v.data_limite > :now
        GROUP BY v.id, v.titulo, v.data_abertura, v.data_limite, v.data_resultado_ate,
                 v.status, v.criado_por, v.data_criacao, e.id, e.texto, e.ordem
        ORDER BY v.data_criacao DESC, e.ordem
    """
    rows = execute_query(query, {"now": now, "user_id": user_id})
    
    return _build_votacao_resultados_from_rows(rows, user_id, force_show=True)


@router.get("/resultados-visiveis", response_model=List[VotacaoResultado])
async def listar_resultados_visiveis(
    current_user: dict = Depends(get_current_user)
):
    """Lista votações encerradas cujos resultados ainda estão visíveis"""
    verificar_e_fechar_votacoes_expiradas()
    now = get_now()
    user_id = current_user["id"]
    
    # Single JOIN query
    query = """
        SELECT v.id, v.titulo, v.data_abertura, v.data_limite, v.data_resultado_ate, 
               v.status, v.criado_por, v.data_criacao,
               e.id as escolha_id, e.texto, e.ordem,
               COUNT(vt.id) as votos,
               MAX(CASE WHEN vt.usuario_id = :user_id THEN e.id END) as user_escolha_id
        FROM votacoes v
        LEFT JOIN votacao_escolhas e ON e.votacao_id = v.id
        LEFT JOIN votos vt ON vt.escolha_id = e.id
        WHERE (v.status = 'FECHADO' OR v.status = 'FINALIZADO')
        AND v.data_resultado_ate >= :now
        GROUP BY v.id, v.titulo, v.data_abertura, v.data_limite, v.data_resultado_ate,
                 v.status, v.criado_por, v.data_criacao, e.id, e.texto, e.ordem
        ORDER BY v.data_criacao DESC, e.ordem
    """
    rows = execute_query(query, {"now": now, "user_id": user_id})
    
    return _build_votacao_resultados_from_rows(rows, user_id)


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
        "ID": votacao["ID"],
        "TITULO": votacao["TITULO"],
        "DATA_ABERTURA": votacao["DATA_ABERTURA"],
        "DATA_LIMITE": votacao["DATA_LIMITE"],
        "DATA_RESULTADO_ATE": votacao["DATA_RESULTADO_ATE"],
        "STATUS": votacao["STATUS"],
        "CRIADO_POR": votacao["CRIADO_POR"],
        "DATA_CRIACAO": votacao["DATA_CRIACAO"]
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
    
    if votacao["STATUS"] != 'ABERTO':
        raise HTTPException(status_code=400, detail="Esta votação não está aberta")
    
    if now < votacao["DATA_ABERTURA"]:
        raise HTTPException(status_code=400, detail="Esta votação ainda não começou")
    
    if now > votacao["DATA_LIMITE"]:
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
                {"escolha_id": voto.escolha_id, "voto_id": voto_existente["ID"]}
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
        "ID": votacao_full["ID"],
        "TITULO": votacao_full["TITULO"],
        "DATA_ABERTURA": votacao_full["DATA_ABERTURA"],
        "DATA_LIMITE": votacao_full["DATA_LIMITE"],
        "DATA_RESULTADO_ATE": votacao_full["DATA_RESULTADO_ATE"],
        "STATUS": votacao_full["STATUS"],
        "CRIADO_POR": votacao_full["CRIADO_POR"],
        "DATA_CRIACAO": votacao_full["DATA_CRIACAO"]
    }
    
    return _build_votacao_resultado(votacao_dict, user_id, force_show=True)


def _build_votacao_resultados_from_rows(rows, user_id: int, force_show: bool = False):
    """Build VotacaoResultado list from pre-JOINed rows (no extra queries)"""
    now = get_now()
    
    # Group by votacao
    votacoes_map = {}
    for row in rows:
        vid = row["ID"]
        if vid not in votacoes_map:
            votacoes_map[vid] = {"votacao": row, "escolhas": {}, "user_escolha": None}
        
        eid = row["ESCOLHA_ID"]
        if eid:
            votacoes_map[vid]["escolhas"][eid] = {
                "id": eid,
                "texto": row["TEXTO"],
                "ordem": row["ORDEM"],
                "votos": row["VOTOS"]
            }
            if row.get("USER_ESCOLHA_ID") and row["USER_ESCOLHA_ID"] == eid:
                votacoes_map[vid]["user_escolha"] = eid
    
    result = []
    for vid, data in votacoes_map.items():
        v = data["votacao"]
        
        # Detect user vote from any row's USER_ESCOLHA_ID
        escolha_usuario = data["user_escolha"]
        if not escolha_usuario:
            for row in rows:
                if row["ID"] == vid and row.get("USER_ESCOLHA_ID"):
                    escolha_usuario = row["USER_ESCOLHA_ID"]
                    break
        
        usuario_votou = escolha_usuario is not None
        
        votacao_aberta = v["STATUS"] == 'ABERTO' and now <= v["DATA_LIMITE"]
        if not usuario_votou and votacao_aberta and not force_show:
            continue
        
        escolhas_list = sorted(data["escolhas"].values(), key=lambda x: x["ordem"])
        total_votos = sum(e["votos"] for e in escolhas_list)
        
        escolhas_resultado = []
        for e in escolhas_list:
            votos = e["votos"]
            porcentagem = (votos / total_votos * 100) if total_votos > 0 else 0
            escolhas_resultado.append(EscolhaResultado(
                id=e["id"],
                texto=e["texto"],
                ordem=e["ordem"],
                votos=votos,
                porcentagem=round(porcentagem, 1)
            ))
        
        result.append(VotacaoResultado(
            id=v["ID"],
            titulo=v["TITULO"],
            data_abertura=v["DATA_ABERTURA"],
            data_limite=v["DATA_LIMITE"],
            data_resultado_ate=v["DATA_RESULTADO_ATE"],
            status=v["STATUS"],
            total_votos=total_votos,
            escolhas=escolhas_resultado,
            usuario_votou=usuario_votou,
            escolha_usuario=escolha_usuario
        ))
    
    return result


def _build_votacao_resultado(votacao_dict: dict, user_id: int, force_show: bool = False) -> VotacaoResultado:
    """Helper para construir VotacaoResultado com porcentagens (single votacao)"""
    votacao_id = votacao_dict["ID"]
    
    # Single query for escolhas + vote counts + user vote
    query = """
        SELECT :votacao_id as id, e.id as escolha_id, e.texto, e.ordem,
               COUNT(v.id) as votos,
               MAX(CASE WHEN v.usuario_id = :user_id THEN e.id END) as user_escolha_id
        FROM votacao_escolhas e
        LEFT JOIN votos v ON e.id = v.escolha_id
        WHERE e.votacao_id = :votacao_id
        GROUP BY e.id, e.texto, e.ordem
        ORDER BY e.ordem
    """
    escolhas = execute_query(query, {"votacao_id": votacao_id, "user_id": user_id})
    
    escolha_usuario = None
    for e in escolhas:
        if e.get("USER_ESCOLHA_ID"):
            escolha_usuario = e["USER_ESCOLHA_ID"]
            break
    
    usuario_votou = escolha_usuario is not None
    
    now = get_now()
    votacao_aberta = votacao_dict["STATUS"] == 'ABERTO' and now <= votacao_dict["DATA_LIMITE"]
    
    if not usuario_votou and votacao_aberta and not force_show:
        return None
    
    total_votos = sum(e["VOTOS"] for e in escolhas)
    
    escolhas_resultado = []
    for e in escolhas:
        votos = e["VOTOS"]
        porcentagem = (votos / total_votos * 100) if total_votos > 0 else 0
        escolhas_resultado.append(EscolhaResultado(
            id=e["ESCOLHA_ID"],
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
