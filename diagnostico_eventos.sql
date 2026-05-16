-- ============================================================
-- DIAGNÓSTICO: Verificar eventos e a coluna TIPO
-- ============================================================
-- Execute este script para diagnosticar o problema
-- ============================================================

-- 1. Verificar estrutura da coluna TIPO
SELECT column_name, data_type, data_default, nullable
FROM user_tab_columns
WHERE table_name = 'EVENTOS'
AND column_name = 'TIPO';

-- 2. Ver todos os eventos com seus dados
SELECT id, data_evento, status, data_limite, tipo,
       CASE 
           WHEN data_limite > SYSTIMESTAMP THEN 'VÁLIDO'
           ELSE 'EXPIRADO'
       END AS validade
FROM eventos
ORDER BY data_evento DESC;

-- 3. Verificar eventos que deveriam aparecer (ABERTO e não expirado)
SELECT id, data_evento, status, data_limite, tipo
FROM eventos
WHERE status = 'ABERTO'
AND data_limite > SYSTIMESTAMP
ORDER BY data_evento ASC;

-- 4. Atualizar eventos que têm status ABERTO mas tipo NULL
UPDATE eventos
SET tipo = 'NORMAL'
WHERE status = 'ABERTO'
AND tipo IS NULL;

COMMIT;

-- 5. Verificar novamente após o update
SELECT id, data_evento, status, data_limite, tipo,
       CASE 
           WHEN data_limite > SYSTIMESTAMP THEN 'VÁLIDO'
           ELSE 'EXPIRADO'
       END AS validade
FROM eventos
WHERE status = 'ABERTO'
ORDER BY data_evento ASC;
