-- Tabela de Feedbacks dos Usuários
CREATE TABLE feedbacks (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id NUMBER,
    categoria VARCHAR2(30) NOT NULL CHECK (categoria IN ('ELOGIO', 'SUGESTAO', 'PROBLEMA', 'OUTRO')),
    mensagem VARCHAR2(1000) NOT NULL,
    anonimo NUMBER(1) DEFAULT 0 CHECK (anonimo IN (0, 1)),
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_feedback_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

CREATE INDEX idx_feedback_data ON feedbacks(data_criacao DESC);
