from fastapi import APIRouter, HTTPException, status, Depends
from typing import Dict, Optional
from pydantic import BaseModel
from auth import get_current_admin_user
from database import execute_query, get_db_connection

router = APIRouter(prefix="/pizza-config", tags=["Pizza Config"])

class PizzaConfigUpdate(BaseModel):
    """Configurações de pizza para um evento"""
    pairing_overrides: Dict[str, str] = {}  # { halfId1: halfId2 }
    sector_overrides: Dict[str, str] = {}   # { pizzaId: 'STI' | 'SGS' }

class PizzaConfigResponse(BaseModel):
    evento_id: int
    pairing_overrides: Dict[str, str]
    sector_overrides: Dict[str, str]

@router.get("/{evento_id}", response_model=PizzaConfigResponse)
async def get_pizza_config(
    evento_id: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """Obtém as configurações de pizza de um evento"""
    import json
    
    query = """
        SELECT pairing_overrides, sector_overrides
        FROM pizza_configs
        WHERE evento_id = :evento_id
    """
    
    pairing = {}
    sector = {}
    
    # Read CLOB within connection context
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, {"evento_id": evento_id})
        result = cursor.fetchone()
        
        if result:
            # Read LOB while connection is open
            pairing_val = result[0].read() if result[0] and hasattr(result[0], 'read') else result[0]
            sector_val = result[1].read() if result[1] and hasattr(result[1], 'read') else result[1]
            
            if pairing_val:
                pairing = json.loads(pairing_val) if isinstance(pairing_val, str) else {}
            if sector_val:
                sector = json.loads(sector_val) if isinstance(sector_val, str) else {}
        
        cursor.close()
    
    return PizzaConfigResponse(
        evento_id=evento_id,
        pairing_overrides=pairing,
        sector_overrides=sector
    )

@router.put("/{evento_id}", response_model=PizzaConfigResponse)
async def save_pizza_config(
    evento_id: int,
    config: PizzaConfigUpdate,
    current_user: dict = Depends(get_current_admin_user)
):
    """Salva as configurações de pizza de um evento"""
    
    import json
    pairing_json = json.dumps(config.pairing_overrides)
    sector_json = json.dumps(config.sector_overrides)
    
    # Check if config exists
    check_query = """
        SELECT 1 FROM pizza_configs WHERE evento_id = :evento_id
    """
    exists = execute_query(check_query, {"evento_id": evento_id}, fetch_one=True)
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        if exists:
            # Update existing
            update_query = """
                UPDATE pizza_configs 
                SET pairing_overrides = :pairing, sector_overrides = :sector
                WHERE evento_id = :evento_id
            """
            cursor.execute(update_query, {
                "evento_id": evento_id,
                "pairing": pairing_json,
                "sector": sector_json
            })
        else:
            # Insert new
            insert_query = """
                INSERT INTO pizza_configs (evento_id, pairing_overrides, sector_overrides)
                VALUES (:evento_id, :pairing, :sector)
            """
            cursor.execute(insert_query, {
                "evento_id": evento_id,
                "pairing": pairing_json,
                "sector": sector_json
            })
        
        conn.commit()
        cursor.close()
    
    return PizzaConfigResponse(
        evento_id=evento_id,
        pairing_overrides=config.pairing_overrides,
        sector_overrides=config.sector_overrides
    )
