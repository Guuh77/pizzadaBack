import oracledb
import os
from dotenv import load_dotenv

load_dotenv()

# Configurações do banco de dados
DB_USER = os.getenv("DB_USER", "system")
DB_PASSWORD = os.getenv("DB_PASSWORD", "admin")
DB_DSN = os.getenv("DB_DSN", "localhost/XE")

def run_migration():
    print("Iniciando migração da tabela evento_acessos...")
    
    try:
        connection = oracledb.connect(
            user=DB_USER,
            password=DB_PASSWORD,
            dsn=DB_DSN
        )
        cursor = connection.cursor()
        
        # Ler o arquivo SQL
        with open("migrate_create_acessos.sql", "r", encoding="utf-8") as f:
            sql_script = f.read()
            
        # Separar comandos por ponto e vírgula
        commands = sql_script.split(";")
        
        for command in commands:
            command = command.strip()
            if command:
                try:
                    print(f"Executando: {command[:50]}...")
                    cursor.execute(command)
                except oracledb.DatabaseError as e:
                    error, = e.args
                    if error.code == 955: # ORA-00955: name is already used by an existing object
                        print("Tabela ou índice já existe. Pulando...")
                    else:
                        print(f"Erro ao executar comando: {e}")
                        raise e
        
        connection.commit()
        print("Migração concluída com sucesso!")
        
    except Exception as e:
        print(f"Erro fatal na migração: {e}")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'connection' in locals(): connection.close()

if __name__ == "__main__":
    run_migration()
