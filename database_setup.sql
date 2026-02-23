-- Script de criação do banco de dados para Pizzada do Roger
-- Execute este script no seu Oracle Database

-- Tabela de Usuários
CREATE TABLE usuarios (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome_completo VARCHAR2(200) NOT NULL,
    senha_hash VARCHAR2(255) NOT NULL,
    setor VARCHAR2(100) NOT NULL,
    is_admin NUMBER(1) DEFAULT 0 CHECK (is_admin IN (0, 1)),
    ativo NUMBER(1) DEFAULT 1 CHECK (ativo IN (0, 1)),
    data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_usuario_nome UNIQUE (nome_completo)
);

-- Tabela de Sabores de Pizza
CREATE TABLE sabores_pizza (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome VARCHAR2(100) NOT NULL,
    preco_pedaco NUMBER(10, 2) NOT NULL,
    ativo NUMBER(1) DEFAULT 1 CHECK (ativo IN (0, 1)),
    data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_sabor_nome UNIQUE (nome)
);

-- Tabela de Eventos (Pizzadas)
CREATE TABLE eventos (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    data_evento DATE NOT NULL,
    status VARCHAR2(20) DEFAULT 'ABERTO' CHECK (status IN ('ABERTO', 'FECHADO', 'FINALIZADO')),
    data_limite TIMESTAMP NOT NULL,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_evento_data UNIQUE (data_evento)
);

-- Tabela de Pedidos
CREATE TABLE pedidos (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    evento_id NUMBER NOT NULL,
    usuario_id NUMBER NOT NULL,
    valor_total NUMBER(10, 2) NOT NULL,
    valor_frete NUMBER(10, 2) DEFAULT 1.00,
    status VARCHAR2(20) DEFAULT 'PENDENTE' CHECK (status IN ('PENDENTE', 'CONFIRMADO', 'PAGO')),
    data_pedido TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_pedido_evento FOREIGN KEY (evento_id) REFERENCES eventos(id),
    CONSTRAINT fk_pedido_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

-- Tabela de Itens do Pedido (pedaços individuais)
CREATE TABLE itens_pedido (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pedido_id NUMBER NOT NULL,
    sabor_id NUMBER NOT NULL,
    quantidade NUMBER NOT NULL,
    preco_unitario NUMBER(10, 2) NOT NULL,
    subtotal NUMBER(10, 2) NOT NULL,
    CONSTRAINT fk_item_pedido FOREIGN KEY (pedido_id) REFERENCES pedidos(id) ON DELETE CASCADE,
    CONSTRAINT fk_item_sabor FOREIGN KEY (sabor_id) REFERENCES sabores_pizza(id)
);

-- Inserir usuário admin padrão (senha: admin123)
INSERT INTO usuarios (nome_completo, senha_hash, setor, is_admin) 
VALUES ('Administrador', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5agyWyWCS/KK6', 'Administração', 1);

-- Inserir alguns sabores de pizza de exemplo
INSERT INTO sabores_pizza (nome, preco_pedaco) VALUES ('Mussarela', 7.00);
INSERT INTO sabores_pizza (nome, preco_pedaco) VALUES ('Calabresa', 7.50);
INSERT INTO sabores_pizza (nome, preco_pedaco) VALUES ('Quatro Queijos', 9.00);
INSERT INTO sabores_pizza (nome, preco_pedaco) VALUES ('Portuguesa', 8.50);
INSERT INTO sabores_pizza (nome, preco_pedaco) VALUES ('Frango com Catupiry', 8.00);
INSERT INTO sabores_pizza (nome, preco_pedaco) VALUES ('Siciliana', 8.00);
INSERT INTO sabores_pizza (nome, preco_pedaco) VALUES ('Margherita', 7.50);
INSERT INTO sabores_pizza (nome, preco_pedaco) VALUES ('Pepperoni', 9.50);

COMMIT;

-- Criar índices para melhor performance
CREATE INDEX idx_pedido_evento ON pedidos(evento_id);
CREATE INDEX idx_pedido_usuario ON pedidos(usuario_id);
CREATE INDEX idx_item_pedido ON itens_pedido(pedido_id);
CREATE INDEX idx_evento_status ON eventos(status);
