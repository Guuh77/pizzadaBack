-- ============================================================
-- MIGRAÇÃO: Adicionar coluna TIPO na tabela EVENTOS
-- ============================================================
-- Execute este script no Oracle SQL Developer ou SQL*Plus
-- Este script é idempotente (pode ser executado várias vezes)
-- ============================================================

SET SERVEROUTPUT ON;

DECLARE
    v_column_exists NUMBER;
BEGIN
    -- Verificar se a coluna TIPO já existe
    SELECT COUNT(*)
    INTO v_column_exists
    FROM user_tab_columns
    WHERE table_name = 'EVENTOS'
    AND column_name = 'TIPO';
    
    IF v_column_exists = 0 THEN
        -- Coluna não existe, vamos adicionar
        DBMS_OUTPUT.PUT_LINE('Adicionando coluna TIPO na tabela EVENTOS...');
        
        EXECUTE IMMEDIATE '
            ALTER TABLE eventos 
            ADD (tipo VARCHAR2(20) DEFAULT ''NORMAL'' 
                 CHECK (tipo IN (''NORMAL'', ''RELAMPAGO'')))
        ';
        
        DBMS_OUTPUT.PUT_LINE('Coluna TIPO adicionada com sucesso!');
        
        -- Atualizar registros existentes
        UPDATE eventos 
        SET tipo = 'NORMAL' 
        WHERE tipo IS NULL;
        
        DBMS_OUTPUT.PUT_LINE(SQL%ROWCOUNT || ' evento(s) existente(s) atualizado(s)');
        
        COMMIT;
        DBMS_OUTPUT.PUT_LINE('Migração concluída com sucesso!');
    ELSE
        -- Coluna já existe
        DBMS_OUTPUT.PUT_LINE('A coluna TIPO já existe. Nenhuma alteração necessária.');
    END IF;
    
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('ERRO: ' || SQLERRM);
        ROLLBACK;
        RAISE;
END;
/

-- Verificar o resultado
SELECT column_name, data_type, data_default
FROM user_tab_columns
WHERE table_name = 'EVENTOS'
AND column_name = 'TIPO';

-- Verificar eventos
SELECT id, data_evento, status, tipo
FROM eventos
ORDER BY data_evento DESC;
