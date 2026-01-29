-- Diagnóstico: Verificar pedidos no evento 24/11/2025

-- 1. Ver todos os eventos
SELECT id, data_evento, status, data_limite, tipo
FROM eventos
ORDER BY data_evento DESC;

-- 2. Ver pedidos no evento de 24/11/2025  
-- (ajuste o ID conforme necessário)
SELECT p.id, p.evento_id, p.usuario_id, p.valor_total, p.status
FROM pedidos p
JOIN eventos e ON p.evento_id = e.id
WHERE e.data_evento = TO_DATE('2025-11-24', 'YYYY-MM-DD')
ORDER BY p.id;

-- 3. Ver itens de pedido  
SELECT ip.*, p.evento_id
FROM itens_pedido ip
JOIN pedidos p ON ip.pedido_id = p.id
JOIN eventos e ON p.evento_id = e.id
WHERE e.data_evento = TO_DATE('2025-11-24', 'YYYY-MM-DD');

-- 4. Se encontrar pedidos indesejados, DELETE:
-- DELETE FROM itens_pedido WHERE pedido_id IN (
--     SELECT p.id FROM pedidos p
--     JOIN eventos e ON p.evento_id = e.id
--     WHERE e.data_evento = TO_DATE('2025-11-24', 'YYYY-MM-DD')
-- );
-- 
-- DELETE FROM pedidos WHERE evento_id IN (
--     SELECT id FROM eventos
--     WHERE data_evento = TO_DATE('2025-11-24', 'YYYY-MM-DD')
-- );
-- 
-- COMMIT;
