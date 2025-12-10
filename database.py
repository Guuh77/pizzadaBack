import oracledb
from config import get_settings
from contextlib import contextmanager

settings = get_settings()

def get_connection_string():
    """Retorna os parâmetros de conexão do Oracle"""
    return {
        "user": settings.DB_USER,
        "password": settings.DB_PASSWORD,
        "host": settings.DB_HOST,
        "port": settings.DB_PORT,
        "service_name": settings.DB_SID
    }

@contextmanager
def get_db_connection():
    """Context manager para conexão com o banco de dados"""
    connection = None
    try:
        # Usar modo thin (não precisa do Instant Client!)
        connection = oracledb.connect(**get_connection_string())
        yield connection
    except oracledb.Error as e:
        if connection:
            connection.rollback()
        raise e
    finally:
        if connection:
            connection.close()

def get_db_cursor(connection):
    """Retorna um cursor do banco de dados"""
    return connection.cursor()

def execute_query(query, params=None, fetch_one=False, fetch_all=True, commit=False):
    """
    Executa uma query no banco de dados
    
    Args:
        query: SQL query para executar
        params: Parâmetros da query
        fetch_one: Se True, retorna apenas um resultado
        fetch_all: Se True, retorna todos os resultados
        commit: Se True, faz commit após a query
        
    Returns:
        Resultado da query ou None
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            if commit:
                conn.commit()
                return cursor.lastrowid if hasattr(cursor, 'lastrowid') else None
            
            if fetch_one:
                return cursor.fetchone()
            elif fetch_all:
                columns = [col[0] for col in cursor.description] if cursor.description else []
                rows = cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]
            
            return None
        finally:
            cursor.close()