import oracledb
from config import get_settings
from database import get_db_connection

def migrate():
    print("Iniciando migração do banco de dados...")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Adicionar coluna 'tipo' na tabela 'eventos'
        try:
            print("Adicionando coluna 'tipo' na tabela 'eventos'...")
            cursor.execute("ALTER TABLE eventos ADD (tipo VARCHAR2(20) DEFAULT 'NORMAL')")
            print("Coluna 'tipo' adicionada com sucesso.")
        except oracledb.Error as e:
            if "ORA-01430" in str(e): # ORA-01430: column being added already exists in table
                print("Coluna 'tipo' já existe.")
            else:
                print(f"Erro ao adicionar coluna 'tipo': {e}")
                
        # 2. Criar tabela 'evento_acessos'
        try:
            print("Criando tabela 'evento_acessos'...")
            create_table_query = """
            CREATE TABLE evento_acessos (
                evento_id NUMBER NOT NULL,
                usuario_id NUMBER NOT NULL,
                CONSTRAINT pk_evento_acessos PRIMARY KEY (evento_id, usuario_id),
                CONSTRAINT fk_evento_acessos_evento FOREIGN KEY (evento_id) REFERENCES eventos(id) ON DELETE CASCADE,
                CONSTRAINT fk_evento_acessos_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
            """
            cursor.execute(create_table_query)
            print("Tabela 'evento_acessos' criada com sucesso.")
        except oracledb.Error as e:
            if "ORA-00955" in str(e): # ORA-00955: name is already used by an existing object
                print("Tabela 'evento_acessos' já existe.")
            else:
                print(f"Erro ao criar tabela 'evento_acessos': {e}")

        conn.commit()
        cursor.close()
        
    print("Migração concluída.")

if __name__ == "__main__":
    migrate()
