-- Tabela de Acessos a Eventos Relâmpago
CREATE TABLE evento_acessos (
    evento_id NUMBER NOT NULL,
    usuario_id NUMBER NOT NULL,
    CONSTRAINT pk_evento_acesso PRIMARY KEY (evento_id, usuario_id),
    CONSTRAINT fk_acesso_evento FOREIGN KEY (evento_id) REFERENCES eventos(id) ON DELETE CASCADE,
    CONSTRAINT fk_acesso_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
);

-- Índice para performance
CREATE INDEX idx_acesso_evento ON evento_acessos(evento_id);
CREATE INDEX idx_acesso_usuario ON evento_acessos(usuario_id);
