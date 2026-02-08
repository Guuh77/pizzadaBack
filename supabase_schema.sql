-- ============================================================
-- PIZZADA DO LELO - Schema PostgreSQL para Supabase
-- Versão convertida do Oracle Database
-- Execute este script no SQL Editor do Supabase
-- ============================================================

-- Extensões necessárias
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- TABELA: usuarios
-- ============================================================
CREATE TABLE usuarios (
    id SERIAL PRIMARY KEY,
    nome_completo VARCHAR(200) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    senha_hash VARCHAR(255) NOT NULL,
    setor VARCHAR(100) NOT NULL,
    is_admin BOOLEAN DEFAULT FALSE,
    ativo BOOLEAN DEFAULT TRUE,
    data_cadastro TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uk_usuario_nome UNIQUE (nome_completo)
);

-- ============================================================
-- TABELA: sabores_pizza
-- ============================================================
CREATE TABLE sabores_pizza (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    preco_pedaco DECIMAL(10, 2) NOT NULL,
    tipo VARCHAR(20) DEFAULT 'salgada' CHECK (tipo IN ('salgada', 'doce')),
    ativo BOOLEAN DEFAULT TRUE,
    data_cadastro TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uk_sabor_nome UNIQUE (nome)
);

-- ============================================================
-- TABELA: eventos (Pizzadas)
-- ============================================================
CREATE TABLE eventos (
    id SERIAL PRIMARY KEY,
    data_evento DATE NOT NULL,
    status VARCHAR(20) DEFAULT 'ABERTO' CHECK (status IN ('ABERTO', 'FECHADO', 'FINALIZADO')),
    tipo VARCHAR(20) DEFAULT 'NORMAL' CHECK (tipo IN ('NORMAL', 'RELAMPAGO')),
    data_limite TIMESTAMPTZ NOT NULL,
    data_criacao TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uk_evento_data UNIQUE (data_evento)
);

-- ============================================================
-- TABELA: evento_acessos (para eventos RELAMPAGO)
-- ============================================================
CREATE TABLE evento_acessos (
    evento_id INTEGER NOT NULL,
    usuario_id INTEGER NOT NULL,
    PRIMARY KEY (evento_id, usuario_id),
    CONSTRAINT fk_acesso_evento FOREIGN KEY (evento_id) REFERENCES eventos(id) ON DELETE CASCADE,
    CONSTRAINT fk_acesso_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
);

-- ============================================================
-- TABELA: pedidos
-- ============================================================
CREATE TABLE pedidos (
    id SERIAL PRIMARY KEY,
    evento_id INTEGER NOT NULL,
    usuario_id INTEGER NOT NULL,
    valor_total DECIMAL(10, 2) NOT NULL,
    valor_frete DECIMAL(10, 2) DEFAULT 1.00,
    status VARCHAR(20) DEFAULT 'PENDENTE' CHECK (status IN ('PENDENTE', 'CONFIRMADO', 'PAGO')),
    data_pedido TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_pedido_evento FOREIGN KEY (evento_id) REFERENCES eventos(id),
    CONSTRAINT fk_pedido_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

-- ============================================================
-- TABELA: itens_pedido
-- ============================================================
CREATE TABLE itens_pedido (
    id SERIAL PRIMARY KEY,
    pedido_id INTEGER NOT NULL,
    sabor_id INTEGER NOT NULL,
    quantidade INTEGER NOT NULL,
    preco_unitario DECIMAL(10, 2) NOT NULL,
    subtotal DECIMAL(10, 2) NOT NULL,
    CONSTRAINT fk_item_pedido FOREIGN KEY (pedido_id) REFERENCES pedidos(id) ON DELETE CASCADE,
    CONSTRAINT fk_item_sabor FOREIGN KEY (sabor_id) REFERENCES sabores_pizza(id)
);

-- ============================================================
-- TABELA: pizza_configs (configurações de montagem)
-- ============================================================
CREATE TABLE pizza_configs (
    id SERIAL PRIMARY KEY,
    evento_id INTEGER NOT NULL UNIQUE,
    pairing_overrides JSONB DEFAULT '{}',
    sector_overrides JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_pizza_config_evento FOREIGN KEY (evento_id) REFERENCES eventos(id) ON DELETE CASCADE
);

-- ============================================================
-- TABELA: codigos_reset_senha
-- ============================================================
CREATE TABLE codigos_reset_senha (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    codigo VARCHAR(10) NOT NULL,
    data_expiracao TIMESTAMPTZ NOT NULL,
    usado BOOLEAN DEFAULT FALSE,
    data_criacao TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_reset_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
);

-- ============================================================
-- TABELA: votacoes
-- ============================================================
CREATE TABLE votacoes (
    id SERIAL PRIMARY KEY,
    titulo VARCHAR(200) NOT NULL,
    data_abertura TIMESTAMPTZ NOT NULL,
    data_limite TIMESTAMPTZ NOT NULL,
    data_resultado_ate TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) DEFAULT 'ABERTO' CHECK (status IN ('ABERTO', 'FECHADO', 'FINALIZADO')),
    criado_por INTEGER NOT NULL,
    data_criacao TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_votacao_criador FOREIGN KEY (criado_por) REFERENCES usuarios(id)
);

-- ============================================================
-- TABELA: votacao_escolhas
-- ============================================================
CREATE TABLE votacao_escolhas (
    id SERIAL PRIMARY KEY,
    votacao_id INTEGER NOT NULL,
    texto VARCHAR(200) NOT NULL,
    ordem INTEGER NOT NULL,
    CONSTRAINT fk_escolha_votacao FOREIGN KEY (votacao_id) REFERENCES votacoes(id) ON DELETE CASCADE,
    CONSTRAINT uk_escolha_ordem UNIQUE (votacao_id, ordem)
);

-- ============================================================
-- TABELA: votos
-- ============================================================
CREATE TABLE votos (
    id SERIAL PRIMARY KEY,
    escolha_id INTEGER NOT NULL,
    usuario_id INTEGER NOT NULL,
    data_voto TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_voto_escolha FOREIGN KEY (escolha_id) REFERENCES votacao_escolhas(id) ON DELETE CASCADE,
    CONSTRAINT fk_voto_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
    CONSTRAINT uk_voto_unico UNIQUE (escolha_id, usuario_id)
);

-- ============================================================
-- ÍNDICES para performance
-- ============================================================
CREATE INDEX idx_pedido_evento ON pedidos(evento_id);
CREATE INDEX idx_pedido_usuario ON pedidos(usuario_id);
CREATE INDEX idx_item_pedido ON itens_pedido(pedido_id);
CREATE INDEX idx_evento_status ON eventos(status);
CREATE INDEX idx_acesso_evento ON evento_acessos(evento_id);
CREATE INDEX idx_acesso_usuario ON evento_acessos(usuario_id);
CREATE INDEX idx_pizza_configs_evento ON pizza_configs(evento_id);
CREATE INDEX idx_votacao_status ON votacoes(status);
CREATE INDEX idx_votacao_datas ON votacoes(data_abertura, data_limite, data_resultado_ate);
CREATE INDEX idx_escolha_votacao ON votacao_escolhas(votacao_id);
CREATE INDEX idx_voto_escolha ON votos(escolha_id);
CREATE INDEX idx_voto_usuario ON votos(usuario_id);
CREATE INDEX idx_reset_usuario ON codigos_reset_senha(usuario_id);

-- ============================================================
-- TRIGGER: Atualizar updated_at em pizza_configs
-- ============================================================
CREATE OR REPLACE FUNCTION update_pizza_configs_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_pizza_configs_update
    BEFORE UPDATE ON pizza_configs
    FOR EACH ROW
    EXECUTE FUNCTION update_pizza_configs_timestamp();

-- ============================================================
-- FUNÇÃO: Verificar voto único por votação (substitui trigger Oracle)
-- ============================================================
CREATE OR REPLACE FUNCTION check_voto_unico()
RETURNS TRIGGER AS $$
DECLARE
    v_votacao_id INTEGER;
    v_count INTEGER;
BEGIN
    -- Buscar votação da escolha
    SELECT votacao_id INTO v_votacao_id
    FROM votacao_escolhas
    WHERE id = NEW.escolha_id;
    
    -- Verificar se usuário já votou nesta votação
    SELECT COUNT(*) INTO v_count
    FROM votos v
    JOIN votacao_escolhas e ON v.escolha_id = e.id
    WHERE e.votacao_id = v_votacao_id
    AND v.usuario_id = NEW.usuario_id;
    
    IF v_count > 0 THEN
        RAISE EXCEPTION 'Usuário já votou nesta votação';
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_voto_unico_votacao
    BEFORE INSERT ON votos
    FOR EACH ROW
    EXECUTE FUNCTION check_voto_unico();

-- ============================================================
-- DADOS INICIAIS: Usuário Admin (senha: admin123)
-- ============================================================
INSERT INTO usuarios (nome_completo, email, senha_hash, setor, is_admin) 
VALUES ('Administrador', 'admin@pizzada.com', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5agyWyWCS/KK6', 'Administração', TRUE);

-- ============================================================
-- DADOS INICIAIS: Sabores de Pizza
-- ============================================================
INSERT INTO sabores_pizza (nome, preco_pedaco, tipo) VALUES 
    ('Mussarela', 7.00, 'salgada'),
    ('Calabresa', 7.50, 'salgada'),
    ('Quatro Queijos', 9.00, 'salgada'),
    ('Portuguesa', 8.50, 'salgada'),
    ('Frango com Catupiry', 8.00, 'salgada'),
    ('Siciliana', 8.00, 'salgada'),
    ('Margherita', 7.50, 'salgada'),
    ('Pepperoni', 9.50, 'salgada');

-- ============================================================
-- FIM DO SCRIPT
-- ============================================================
