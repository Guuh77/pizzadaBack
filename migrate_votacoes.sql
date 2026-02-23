-- Script de migração: Sistema de Votações
-- Execute este script no Oracle Database

-- Tabela principal de votações
CREATE TABLE votacoes (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    titulo VARCHAR2(200) NOT NULL,
    data_abertura TIMESTAMP NOT NULL,
    data_limite TIMESTAMP NOT NULL,
    data_resultado_ate TIMESTAMP NOT NULL,
    status VARCHAR2(20) DEFAULT 'ABERTO' CHECK (status IN ('ABERTO', 'FECHADO', 'FINALIZADO')),
    criado_por NUMBER NOT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_votacao_criador FOREIGN KEY (criado_por) REFERENCES usuarios(id)
);

-- Tabela de escolhas (cada votação tem 2-4 escolhas)
CREATE TABLE votacao_escolhas (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    votacao_id NUMBER NOT NULL,
    texto VARCHAR2(200) NOT NULL,
    ordem NUMBER NOT NULL,
    CONSTRAINT fk_escolha_votacao FOREIGN KEY (votacao_id) REFERENCES votacoes(id) ON DELETE CASCADE,
    CONSTRAINT uk_escolha_ordem UNIQUE (votacao_id, ordem)
);

-- Tabela de votos (cada usuário vota uma vez por votação)
CREATE TABLE votos (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    escolha_id NUMBER NOT NULL,
    usuario_id NUMBER NOT NULL,
    data_voto TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_voto_escolha FOREIGN KEY (escolha_id) REFERENCES votacao_escolhas(id) ON DELETE CASCADE,
    CONSTRAINT fk_voto_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
    CONSTRAINT uk_voto_unico UNIQUE (escolha_id, usuario_id)
);

-- Criar constraint para garantir voto único por votação (via trigger)
CREATE OR REPLACE TRIGGER trg_voto_unico_votacao
BEFORE INSERT ON votos
FOR EACH ROW
DECLARE
    v_votacao_id NUMBER;
    v_count NUMBER;
BEGIN
    -- Buscar votação da escolha
    SELECT votacao_id INTO v_votacao_id
    FROM votacao_escolhas
    WHERE id = :NEW.escolha_id;
    
    -- Verificar se usuário já votou nesta votação
    SELECT COUNT(*) INTO v_count
    FROM votos v
    JOIN votacao_escolhas e ON v.escolha_id = e.id
    WHERE e.votacao_id = v_votacao_id
    AND v.usuario_id = :NEW.usuario_id;
    
    IF v_count > 0 THEN
        RAISE_APPLICATION_ERROR(-20001, 'Usuário já votou nesta votação');
    END IF;
END;
/

-- Índices para performance
CREATE INDEX idx_votacao_status ON votacoes(status);
CREATE INDEX idx_votacao_datas ON votacoes(data_abertura, data_limite, data_resultado_ate);
CREATE INDEX idx_escolha_votacao ON votacao_escolhas(votacao_id);
CREATE INDEX idx_voto_escolha ON votos(escolha_id);
CREATE INDEX idx_voto_usuario ON votos(usuario_id);

COMMIT;
