import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from config import get_settings

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo


settings = get_settings()
SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")

BOOLEAN_PARAM_NAMES = {"admin", "ativo", "is_admin", "anonimo", "pagamento_liberado"}
JSON_PARAM_NAMES = {"pairing", "sector", "num_overrides"}
BOOLEAN_COLUMNS = ("ativo", "is_admin", "pagamento_liberado", "usado", "anonimo")
UTC_WALL_TIME_COLUMNS = {"DATA_EXPIRACAO"}


def get_connection_string():
    """Retorna a URL de conexao do Supabase/Postgres."""
    return settings.DATABASE_URL


def _postgres_dsn() -> str:
    dsn = get_connection_string()
    if "sslmode=" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    return dsn


def _translate_query(query: str) -> str:
    """Traduz o subconjunto Oracle usado pelo projeto para Postgres."""
    translated = query

    # Oracle bind variables (:nome) -> psycopg named placeholders (%(nome)s)
    translated = re.sub(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", r"%(\1)s", translated)

    # Oracle row limiting -> Postgres LIMIT
    translated = re.sub(
        r"\bFETCH\s+FIRST\s+(\d+)\s+ROWS\s+ONLY\b",
        r"LIMIT \1",
        translated,
        flags=re.IGNORECASE,
    )

    # Boolean columns were NUMBER(1) in Oracle and are boolean in Supabase.
    for column in BOOLEAN_COLUMNS:
        translated = re.sub(
            rf"\b{column}\b\s*=\s*1\b",
            f"{column} = true",
            translated,
            flags=re.IGNORECASE,
        )
        translated = re.sub(
            rf"\b{column}\b\s*=\s*0\b",
            f"{column} = false",
            translated,
            flags=re.IGNORECASE,
        )

    return translated


def _coerce_params(query: str, params: Any):
    if not isinstance(params, dict):
        return params

    coerced = dict(params)
    query_lower = query.lower()

    for name in BOOLEAN_PARAM_NAMES:
        if name in coerced and coerced[name] is not None:
            coerced[name] = bool(coerced[name])

    if "pagamento_liberado" in query_lower and "valor" in coerced:
        coerced["valor"] = bool(coerced["valor"])

    for name in JSON_PARAM_NAMES:
        if name in coerced and not isinstance(coerced[name], Jsonb):
            coerced[name] = Jsonb(coerced[name])

    for name, value in list(coerced.items()):
        if isinstance(value, datetime) and value.tzinfo is None:
            coerced[name] = value.replace(tzinfo=SAO_PAULO_TZ)

    return coerced


def _description_names(description):
    if not description:
        return []
    return [getattr(column, "name", column[0]).upper() for column in description]


def _normalize_row_value(value, column_name=None):
    if isinstance(value, datetime) and value.tzinfo is not None:
        if column_name in UTC_WALL_TIME_COLUMNS:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.astimezone(SAO_PAULO_TZ).replace(tzinfo=None)
    return value


def _normalize_row(row, description=None):
    if row is None:
        return None
    column_names = _description_names(description) if description else []
    return tuple(
        _normalize_row_value(value, column_names[index] if index < len(column_names) else None)
        for index, value in enumerate(row)
    )


class CompatCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=None):
        translated = _translate_query(query)
        coerced_params = _coerce_params(query, params)
        if coerced_params is not None:
            return self._cursor.execute(translated, coerced_params)
        return self._cursor.execute(translated)

    def executemany(self, query, params_seq):
        translated = _translate_query(query)
        coerced = [_coerce_params(query, params) for params in params_seq]
        return self._cursor.executemany(translated, coerced)

    def fetchone(self):
        return _normalize_row(self._cursor.fetchone(), self._cursor.description)

    def fetchall(self):
        return [_normalize_row(row, self._cursor.description) for row in self._cursor.fetchall()]

    def close(self):
        return self._cursor.close()

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount


class CompatConnection:
    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return CompatCursor(self._connection.cursor())

    def commit(self):
        return self._connection.commit()

    def rollback(self):
        return self._connection.rollback()

    def close(self):
        return self._connection.close()


@contextmanager
def get_db_connection():
    """Context manager para conexao com o Supabase/Postgres."""
    connection = None
    try:
        connection = psycopg.connect(_postgres_dsn(), connect_timeout=20)
        connection.execute("set timezone to 'America/Sao_Paulo'")
        yield CompatConnection(connection)
    except psycopg.Error:
        if connection:
            connection.rollback()
        raise
    finally:
        if connection:
            connection.close()


def get_db_cursor(connection):
    """Retorna um cursor do banco de dados."""
    return connection.cursor()


def execute_query(query, params=None, fetch_one=False, fetch_all=True, commit=False):
    """
    Executa uma query no banco de dados.

    Mantem o retorno com chaves em maiusculo para preservar compatibilidade
    com as rotas que antes consumiam o driver Oracle.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)

            if commit:
                conn.commit()
                return None

            if fetch_one:
                row = cursor.fetchone()
                if row and cursor.description:
                    columns = _description_names(cursor.description)
                    return dict(zip(columns, row))
                return row

            if fetch_all:
                columns = _description_names(cursor.description)
                rows = cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]

            return None
        finally:
            cursor.close()
