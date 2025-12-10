from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from routes_auth import router as auth_router
from routes_sabores import router as sabores_router
from routes_eventos import router as eventos_router
from routes_pedidos import router as pedidos_router
from routes_dashboard import router as dashboard_router
from routes_pagamentos import router as pagamentos_router
from routes_pizza_config import router as pizza_config_router

app = FastAPI(
    title="PIZZADA DO LELO API",
    description="API para gerenciamento de pedidos de pizza nos eventos mensais",
    version="1.0.0"
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, especifique os domínios permitidos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrar rotas
app.include_router(auth_router)
app.include_router(sabores_router)
app.include_router(eventos_router)
app.include_router(pedidos_router)
app.include_router(dashboard_router)
app.include_router(pagamentos_router)
app.include_router(pizza_config_router)

# Servir arquivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return {
        "message": "Bem-vindo à PIZZADA DO LELO! 🍕",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/health")
async def health_check():
    """Endpoint para verificar saúde da API"""
    return {"status": "ok", "message": "API está funcionando!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)