from fastapi import APIRouter, HTTPException, status, Depends
import json
from typing import Dict, Optional
from pydantic import BaseModel
from auth import get_current_admin_user
from database import execute_query, get_db_connection

router = APIRouter(prefix="/pizza-config", tags=["Pizza Config"])


def parse_json_value(value):
    if value is None:
        return {}
    if hasattr(value, "read"):
        value = value.read()
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        return json.loads(value)
    return {}

class PizzaConfigUpdate(BaseModel):
    """Configurações de pizza para um evento"""
    pairing_overrides: Dict[str, str] = {}  # { halfId1: halfId2 }
    sector_overrides: Dict[str, str] = {}   # { pizzaId: 'STI' | 'SGS' }
    number_overrides: Dict[str, int] = {}   # { pizzaId: assignedNumber }

class PizzaConfigResponse(BaseModel):
    evento_id: int
    pairing_overrides: Dict[str, str]
    sector_overrides: Dict[str, str]
    number_overrides: Dict[str, int]

@router.get("/{evento_id}", response_model=PizzaConfigResponse)
async def get_pizza_config(
    evento_id: int,
    current_user: dict = Depends(get_current_admin_user)
):
    """Obtém as configurações de pizza de um evento"""
    query = """
        SELECT pairing_overrides, sector_overrides, number_overrides
        FROM pizza_configs
        WHERE evento_id = :evento_id
    """
    
    pairing = {}
    sector = {}
    number = {}
    
    # Read CLOB within connection context
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, {"evento_id": evento_id})
        result = cursor.fetchone()
        
        if result:
            pairing = parse_json_value(result[0])
            sector = parse_json_value(result[1])
            number = {k: int(v) for k, v in parse_json_value(result[2]).items()}
        
        cursor.close()
    
    return PizzaConfigResponse(
        evento_id=evento_id,
        pairing_overrides=pairing,
        sector_overrides=sector,
        number_overrides=number
    )

@router.put("/{evento_id}", response_model=PizzaConfigResponse)
async def save_pizza_config(
    evento_id: int,
    config: PizzaConfigUpdate,
    current_user: dict = Depends(get_current_admin_user)
):
    """Salva as configurações de pizza de um evento"""
    
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
                SET pairing_overrides = :pairing, sector_overrides = :sector, number_overrides = :num_overrides
                WHERE evento_id = :evento_id
            """
            cursor.execute(update_query, {
                "evento_id": evento_id,
                "pairing": config.pairing_overrides,
                "sector": config.sector_overrides,
                "num_overrides": config.number_overrides
            })
        else:
            # Insert new
            insert_query = """
                INSERT INTO pizza_configs (evento_id, pairing_overrides, sector_overrides, number_overrides)
                VALUES (:evento_id, :pairing, :sector, :num_overrides)
            """
            cursor.execute(insert_query, {
                "evento_id": evento_id,
                "pairing": config.pairing_overrides,
                "sector": config.sector_overrides,
                "num_overrides": config.number_overrides
            })
        
        conn.commit()
        cursor.close()
    
    return PizzaConfigResponse(
        evento_id=evento_id,
        pairing_overrides=config.pairing_overrides,
        sector_overrides=config.sector_overrides,
        number_overrides=config.number_overrides
    )
