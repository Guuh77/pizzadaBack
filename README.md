# Pizzada do Roger - Backend

API REST desenvolvida em Python com FastAPI para gerenciar pedidos de pizza nos eventos mensais.

## 🚀 Tecnologias

- Python 3.9+
- FastAPI
- Oracle Database
- JWT para autenticação
- cx_Oracle para conexão com banco

## 📋 Pré-requisitos

- Python 3.9 ou superior
- Acesso ao Oracle Database
- pip (gerenciador de pacotes Python)

## 🔧 Instalação

1. **Clone o repositório e entre na pasta do backend:**
```bash
cd backend
```

2. **Crie um ambiente virtual (recomendado):**
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

3. **Instale as dependências:**
```bash
pip install -r requirements.txt
```

4. **Configure as variáveis de ambiente:**

Copie o arquivo `.env.example` para `.env` e preencha com suas credenciais:
```bash
cp .env.example .env
```

Edite o arquivo `.env` com suas credenciais do Oracle.

5. **Execute o script SQL para criar as tabelas:**

Conecte-se ao seu Oracle Database e execute o arquivo `database_setup.sql`

## ▶️ Executando o servidor

```bash
python main.py
```

Ou usando uvicorn diretamente:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

A API estará disponível em: `http://localhost:8000`

Documentação interativa (Swagger): `http://localhost:8000/docs`

## 📚 Endpoints Principais

### Autenticação
- `POST /auth/register` - Registrar novo usuário
- `POST /auth/login` - Fazer login
- `GET /auth/me` - Obter dados do usuário logado

### Sabores (Admin)
- `GET /sabores/` - Listar sabores
- `POST /sabores/` - Criar sabor (admin)
- `PUT /sabores/{id}` - Atualizar sabor (admin)
- `DELETE /sabores/{id}` - Deletar sabor (admin)

### Eventos (Admin cria, todos visualizam)
- `GET /eventos/` - Listar eventos
- `GET /eventos/ativo` - Obter evento ativo
- `POST /eventos/` - Criar evento (admin)
- `PUT /eventos/{id}` - Atualizar evento (admin)

### Pedidos
- `POST /pedidos/` - Criar pedido
- `GET /pedidos/meus-pedidos` - Listar meus pedidos
- `GET /pedidos/{id}` - Obter detalhes do pedido
- `DELETE /pedidos/{id}` - Cancelar pedido

### Dashboard
- `GET /dashboard/evento/{id}` - Dashboard do evento
- `GET /dashboard/evento/{id}/oportunidades` - Oportunidades para completar pizzas
- `GET /dashboard/evento/{id}/sugestao-combinacao` - Sugestões de meio a meio

## 🔐 Autenticação

A API usa JWT (JSON Web Tokens) para autenticação. Após fazer login, inclua o token no header:

```
Authorization: Bearer {seu_token}
```

## 👤 Usuário Admin Padrão

**Nome:** Administrador  
**Senha:** admin123  
**Setor:** Administração

⚠️ **IMPORTANTE:** Altere esta senha em produção!

## 🚢 Deploy no Render.com

1. Faça push do código para o GitHub
2. Acesse https://render.com
3. Crie um novo "Web Service"
4. Conecte seu repositório
5. Configure:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Adicione as variáveis de ambiente (.env)
7. Deploy!

## 📝 Estrutura do Projeto

```
backend/
├── main.py                 # Arquivo principal da API
├── config.py              # Configurações
├── database.py            # Conexão com Oracle
├── models.py              # Modelos Pydantic
├── auth.py                # Autenticação e segurança
├── routes_auth.py         # Rotas de autenticação
├── routes_sabores.py      # Rotas de sabores
├── routes_eventos.py      # Rotas de eventos
├── routes_pedidos.py      # Rotas de pedidos
├── routes_dashboard.py    # Rotas de dashboard
├── requirements.txt       # Dependências
├── .env                   # Variáveis de ambiente (não commitar!)
└── database_setup.sql     # Script SQL para criar tabelas
```

## 🐛 Troubleshooting

**Erro ao conectar com Oracle:**
- Verifique se as credenciais estão corretas no `.env`
- Teste a conexão com o banco usando SQL Developer ou similar

**Erro de importação cx_Oracle:**
- Certifique-se de que o Oracle Instant Client está instalado
- No Windows, pode ser necessário adicionar ao PATH

**Erro de CORS:**
- Verifique se o frontend está na lista de origens permitidas no `main.py`

## 📄 Licença

Este projeto é privado e de uso interno.
