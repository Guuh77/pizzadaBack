"""
Script para adicionar a coluna 'tipo' na tabela eventos
Execute este script uma vez para atualizar o banco de dados.

Como executar:
1. Navegue até a pasta pizzadaBack-main
2. Execute: python migrate_add_tipo.py
"""

import oracledb
from database import get_db_connection

def migrate_add_tipo():
    print("=" * 60)
    print("MIGRAÇÃO: Adicionando coluna 'tipo' na tabela eventos")
    print("=" * 60)
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Verificar se a coluna já existe
            check_query = """
                SELECT COUNT(*) 
                FROM user_tab_columns 
                WHERE table_name = 'EVENTOS' 
                AND column_name = 'TIPO'
            """
            cursor.execute(check_query)
            exists = cursor.fetchone()[0]
            
            if exists > 0:
                print("✅ A coluna 'tipo' já existe na tabela eventos.")
                print("Nenhuma alteração necessária.")
            else:
                print("Adicionando coluna 'tipo' na tabela eventos...")
                
                # Adicionar a coluna
                alter_query = """
                    ALTER TABLE eventos 
                    ADD (tipo VARCHAR2(20) DEFAULT 'NORMAL' 
                         CHECK (tipo IN ('NORMAL', 'RELAMPAGO')))
                """
                cursor.execute(alter_query)
                
                # Atualizar registros existentes
                update_query = """
                    UPDATE eventos 
                    SET tipo = 'NORMAL' 
                    WHERE tipo IS NULL
                """
                cursor.execute(update_query)
                rows_updated = cursor.rowcount
                
                conn.commit()
                
                print(f"✅ Coluna 'tipo' adicionada com sucesso!")
                print(f"✅ {rows_updated} evento(s) existente(s) atualizado(s) para tipo='NORMAL'")
            
            cursor.close()
            
        print("=" * 60)
        print("MIGRAÇÃO CONCLUÍDA COM SUCESSO!")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ ERRO durante a migração: {e}")
        print("Por favor, verifique a conexão com o banco de dados.")
        raise

if __name__ == "__main__":
    migrate_add_tipo()
