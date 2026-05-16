import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import oracledb
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb


APP_TABLES_DROP_ORDER = [
    "feedback",
    "feedbacks",
    "auditoria_logs",
    "votos",
    "votacao_escolhas",
    "votacoes",
    "codigos_reset_senha",
    "pizza_configs",
    "itens_pedido",
    "pedidos",
    "evento_acessos",
    "eventos",
    "sabores_pizza",
    "usuarios",
]

MIGRATION_ORDER = [
    "usuarios",
    "sabores_pizza",
    "eventos",
    "evento_acessos",
    "pedidos",
    "itens_pedido",
    "pizza_configs",
    "codigos_reset_senha",
    "votacoes",
    "votacao_escolhas",
    "votos",
    "feedbacks",
    "auditoria_logs",
]

TABLE_COLUMNS = {
    "usuarios": [
        "id", "nome_completo", "senha_hash", "setor", "is_admin", "ativo",
        "data_cadastro", "email",
    ],
    "sabores_pizza": [
        "id", "nome", "preco_pedaco", "ativo", "data_cadastro", "descricao", "tipo",
    ],
    "eventos": [
        "id", "data_evento", "status", "data_limite", "data_criacao", "nome",
        "tipo", "pagamento_liberado",
    ],
    "evento_acessos": ["evento_id", "usuario_id"],
    "pedidos": [
        "id", "evento_id", "usuario_id", "valor_total", "valor_frete", "status",
        "data_pedido",
    ],
    "itens_pedido": [
        "id", "pedido_id", "sabor_id", "quantidade", "preco_unitario", "subtotal",
    ],
    "pizza_configs": [
        "id", "evento_id", "pairing_overrides", "sector_overrides", "created_at",
        "updated_at", "number_overrides",
    ],
    "codigos_reset_senha": [
        "id", "usuario_id", "codigo", "data_expiracao", "usado", "data_criacao",
    ],
    "votacoes": [
        "id", "titulo", "data_abertura", "data_limite", "data_resultado_ate",
        "status", "criado_por", "data_criacao",
    ],
    "votacao_escolhas": ["id", "votacao_id", "texto", "ordem"],
    "votos": ["id", "escolha_id", "usuario_id", "data_voto"],
    "feedbacks": ["id", "usuario_id", "categoria", "mensagem", "anonimo", "data_criacao"],
    "auditoria_logs": ["id", "usuario_id", "acao", "detalhes", "ip_address", "data_hora"],
}

BOOLEAN_COLUMNS = {
    "usuarios": {"is_admin", "ativo"},
    "sabores_pizza": {"ativo"},
    "eventos": {"pagamento_liberado"},
    "codigos_reset_senha": {"usado"},
    "feedbacks": {"anonimo"},
}

JSON_COLUMNS = {
    "pizza_configs": {"pairing_overrides", "sector_overrides", "number_overrides"},
}

SEQUENCE_TABLES = [
    table for table in MIGRATION_ORDER
    if table != "evento_acessos"
]


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variavel de ambiente obrigatoria ausente: {name}")
    return value


def oracle_connection():
    return oracledb.connect(
        user=required_env("DB_USER"),
        password=required_env("DB_PASSWORD"),
        host=required_env("DB_HOST"),
        port=int(os.getenv("DB_PORT", "1521")),
        service_name=required_env("DB_SID"),
    )


def supabase_connection():
    dsn = required_env("DATABASE_URL")
    if "sslmode=" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    return psycopg.connect(dsn, connect_timeout=20)


def read_lob(value):
    if value is not None and hasattr(value, "read"):
        return value.read()
    return value


def normalize_value(table: str, column: str, value):
    value = read_lob(value)

    if column in BOOLEAN_COLUMNS.get(table, set()):
        return None if value is None else bool(value)

    if column in JSON_COLUMNS.get(table, set()):
        if value in (None, ""):
            return Jsonb({})
        if isinstance(value, (dict, list)):
            return Jsonb(value)
        return Jsonb(json.loads(value))

    if isinstance(value, Decimal):
        return value

    if isinstance(value, (datetime, date)):
        return value

    return value


def fetch_oracle_rows(cursor, table: str):
    columns = TABLE_COLUMNS[table]
    order_by = "id" if "id" in columns else ", ".join(columns)
    cursor.execute(f"select {', '.join(columns)} from {table} order by {order_by}")
    fetched_columns = [desc[0].lower() for desc in cursor.description]

    rows = []
    for raw_row in cursor.fetchall():
        row = dict(zip(fetched_columns, raw_row))
        rows.append([normalize_value(table, column, row[column]) for column in columns])
    return rows


def drop_app_tables(cursor):
    for table in APP_TABLES_DROP_ORDER:
        cursor.execute(sql.SQL("drop table if exists {} cascade").format(sql.Identifier(table)))


def create_schema(cursor):
    schema_path = Path(__file__).with_name("supabase_schema_final.sql")
    cursor.execute(schema_path.read_text(encoding="utf-8"))


def insert_rows(cursor, table: str, rows: list[list], batch_size: int = 500):
    if not rows:
        return

    columns = TABLE_COLUMNS[table]
    statement = sql.SQL("insert into {} ({}) values ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )

    for start in range(0, len(rows), batch_size):
        cursor.executemany(statement, rows[start:start + batch_size])


def reset_sequence(cursor, table: str):
    cursor.execute(
        """
        select pg_get_serial_sequence(%s, 'id')
        """,
        (table,),
    )
    sequence_name = cursor.fetchone()[0]
    if not sequence_name:
        return

    cursor.execute(
        sql.SQL(
            "select setval(%s, coalesce((select max(id) from {}), 0) + 1, false)"
        ).format(sql.Identifier(table)),
        (sequence_name,),
    )


def count_rows(cursor, table: str) -> int:
    cursor.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table)))
    return int(cursor.fetchone()[0])


def validate_counts(oracle_cursor, pg_cursor):
    mismatches = []
    summary = []

    for table in MIGRATION_ORDER:
        oracle_cursor.execute(f"select count(*) from {table}")
        oracle_count = int(oracle_cursor.fetchone()[0])
        supabase_count = count_rows(pg_cursor, table)
        summary.append((table, oracle_count, supabase_count))

        if oracle_count != supabase_count:
            mismatches.append((table, oracle_count, supabase_count))

    return summary, mismatches


def validate_foreign_keys(cursor):
    checks = {
        "pedidos_eventos_orfaos": """
            select count(*) from pedidos p left join eventos e on e.id = p.evento_id
            where e.id is null
        """,
        "pedidos_usuarios_orfaos": """
            select count(*) from pedidos p left join usuarios u on u.id = p.usuario_id
            where u.id is null
        """,
        "itens_pedidos_orfaos": """
            select count(*) from itens_pedido i left join pedidos p on p.id = i.pedido_id
            where p.id is null
        """,
        "itens_sabores_orfaos": """
            select count(*) from itens_pedido i left join sabores_pizza s on s.id = i.sabor_id
            where s.id is null
        """,
        "votos_escolhas_orfaos": """
            select count(*) from votos v left join votacao_escolhas e on e.id = v.escolha_id
            where e.id is null
        """,
        "votos_usuarios_orfaos": """
            select count(*) from votos v left join usuarios u on u.id = v.usuario_id
            where u.id is null
        """,
    }

    failures = []
    for name, query in checks.items():
        cursor.execute(query)
        count = int(cursor.fetchone()[0])
        if count:
            failures.append((name, count))
    return failures


def main():
    with oracle_connection() as oracle_conn, supabase_connection() as pg_conn:
        oracle_cursor = oracle_conn.cursor()
        pg_conn.execute("set timezone to 'America/Sao_Paulo'")

        with pg_conn.cursor() as pg_cursor:
            print("Recriando schema da Pizzada no Supabase...")
            drop_app_tables(pg_cursor)
            create_schema(pg_cursor)

            print("Copiando dados Oracle -> Supabase...")
            for table in MIGRATION_ORDER:
                rows = fetch_oracle_rows(oracle_cursor, table)
                insert_rows(pg_cursor, table, rows)
                print(f"  {table}: {len(rows)} linhas")

            print("Ajustando sequencias...")
            for table in SEQUENCE_TABLES:
                reset_sequence(pg_cursor, table)

            print("Validando contagens...")
            summary, mismatches = validate_counts(oracle_cursor, pg_cursor)
            for table, oracle_count, supabase_count in summary:
                print(f"  {table}: Oracle={oracle_count} Supabase={supabase_count}")

            fk_failures = validate_foreign_keys(pg_cursor)
            if mismatches or fk_failures:
                pg_conn.rollback()
                raise RuntimeError(
                    "Validacao falhou. "
                    f"Contagens divergentes: {mismatches}. "
                    f"FKs invalidas: {fk_failures}"
                )

        pg_conn.commit()
        oracle_cursor.close()

    print("Migracao concluida com sucesso.")


if __name__ == "__main__":
    main()
