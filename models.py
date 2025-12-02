from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime, date

# Modelos de Usuário
# Modelos de Usuário (Atualizados)
class UsuarioBase(BaseModel):
    nome_completo: str = Field(..., min_length=3, max_length=200)
    setor: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., max_length=100) # NOVO

class UsuarioCreate(UsuarioBase):
    senha: str = Field(..., min_length=6)
    is_admin: bool = False

class UsuarioLogin(BaseModel):
    email: str # MUDOU de nome_completo para email
    senha: str

class UsuarioResponse(UsuarioBase):
    id: int
    is_admin: bool
    ativo: bool
    data_cadastro: Optional[datetime] = None

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UsuarioResponse


# Modelos de Sabor de Pizza
class SaborPizzaBase(BaseModel):
    nome: str = Field(..., min_length=3, max_length=100)
    preco_pedaco: float = Field(..., gt=0)
    descricao: Optional[str] = Field(None, max_length=500)
    # CAMPO NOVO: Tipo de pizza (SALGADA ou DOCE)
    tipo: str = Field("SALGADA", pattern="^(SALGADA|DOCE)$")

class SaborPizzaCreate(SaborPizzaBase):
    pass

class SaborPizzaUpdate(BaseModel):
    nome: Optional[str] = Field(None, min_length=3, max_length=100)
    preco_pedaco: Optional[float] = Field(None, gt=0)
    # CAMPO NOVO ADICIONADO PARA EDIÇÃO:
    descricao: Optional[str] = Field(None, max_length=500)
    tipo: Optional[str] = Field(None, pattern="^(SALGADA|DOCE)$")
    ativo: Optional[bool] = None

class SaborPizzaResponse(SaborPizzaBase):
    id: int
    ativo: bool
    data_cadastro: Optional[datetime] = None



# Modelos de Evento
# Modelos de Evento
class EventoBase(BaseModel):
    data_evento: date
    data_limite: datetime
    nome: Optional[str] = None
    tipo: Optional[str] = Field("NORMAL", pattern="^(NORMAL|RELAMPAGO)$") 

class EventoCreate(EventoBase):
    pass

class EventoCreateRequest(EventoCreate):
    """Modelo extendido para criação de eventos com controle de acesso"""
    allowed_users: Optional[List[int]] = None

class EventoUpdate(BaseModel):
    nome: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(ABERTO|FECHADO|FINALIZADO)$")
    data_limite: Optional[datetime] = None
    tipo: Optional[str] = Field(None, pattern="^(NORMAL|RELAMPAGO)$")

class EventoResponse(EventoBase):
    id: int
    status: str
    data_criacao: Optional[datetime] = None
    tipo: str

# Modelos de Pedido
class ItemPedidoCreate(BaseModel):
    sabor_id: int
    quantidade: int = Field(..., gt=0, le=8)

class ItemPedidoResponse(BaseModel):
    id: int
    sabor_id: int
    sabor_nome: str
    quantidade: int
    preco_unitario: float
    subtotal: float

class PedidoCreate(BaseModel):
    evento_id: int
    itens: List[ItemPedidoCreate] = Field(..., min_items=1)

class PedidoResponse(BaseModel):
    id: int
    evento_id: int
    usuario_id: int
    usuario_nome: str
    usuario_setor: str
    valor_total: float
    valor_frete: float
    status: str
    data_pedido: Optional[datetime] = None
    itens: List[ItemPedidoResponse]

class PedidoUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern="^(PENDENTE|AGUARDANDO_CONFIRMACAO|CONFIRMADO|PAGO)$")

# Modelos de Dashboard
class EstatisticasPizza(BaseModel):
    sabor_id: int
    sabor_nome: str
    total_pedacos: int
    pizzas_completas: int  # quantas pizzas de 8 pedaços
    pedacos_restantes: int  # pedaços que não fecham uma pizza
    valor_total: float

class DashboardResponse(BaseModel):
    evento_id: int
    data_evento: date
    status: str
    total_participantes: int
    total_pedidos: int
    valor_total_evento: float
    estatisticas_por_sabor: List[EstatisticasPizza]

class ResumoEvento(BaseModel):
    evento: EventoResponse
    total_participantes: int
    total_pedidos: int
    total_pizzas: int
    valor_total: float

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    codigo: str = Field(..., min_length=6, max_length=6)
    nova_senha: str = Field(..., min_length=6)

class MessageResponse(BaseModel):
    message: str