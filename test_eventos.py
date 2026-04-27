"""
Script para testar a API de eventos diretamente
"""
import requests
import os

# URL do backend local
BASE_URL = "http://localhost:8000"

# Credenciais via variáveis de ambiente (NUNCA hardcode no código!)
TEST_EMAIL = os.getenv("TEST_ADMIN_EMAIL", "")
TEST_PASSWORD = os.getenv("TEST_ADMIN_PASSWORD", "")

if not TEST_EMAIL or not TEST_PASSWORD:
    print("❌ Configure as variáveis de ambiente TEST_ADMIN_EMAIL e TEST_ADMIN_PASSWORD")
    print("   Exemplo: set TEST_ADMIN_EMAIL=admin@example.com")
    print("   Exemplo: set TEST_ADMIN_PASSWORD=sua_senha")
    exit(1)

print("=" * 60)
print("TESTE: Verificando eventos")
print("=" * 60)

try:
    # Tentar buscar todos os eventos (sem autenticação primeiro)
    print("\n1. Buscando todos os eventos...")
    response = requests.get(f"{BASE_URL}/eventos/")
    
    if response.status_code == 401:
        print("❌ Precisa de autenticação. Vamos fazer login primeiro.")
        
        # Fazer login
        print("\n2. Fazendo login...")
        login_data = {
            "email": TEST_EMAIL,
            "senha": TEST_PASSWORD
        }
        
        login_response = requests.post(f"{BASE_URL}/auth/login", json=login_data)
        
        if login_response.status_code == 200:
            token = login_response.json()["access_token"]
            print("✅ Login bem-sucedido!")
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Tentar novamente com autenticação
            print("\n3. Buscando evento ativo...")
            evento_response = requests.get(f"{BASE_URL}/eventos/ativo", headers=headers)
            
            if evento_response.status_code == 200:
                evento = evento_response.json()
                print(f"✅ Evento ativo encontrado:")
                print(f"   ID: {evento['id']}")
                print(f"   Data: {evento['data_evento']}")
                print(f"   Status: {evento['status']}")
                print(f"   Tipo: {evento.get('tipo', 'N/A')}")
                print(f"   Data Limite: {evento['data_limite']}")
            else:
                print(f"❌ Erro ao buscar evento ativo: {evento_response.status_code}")
                print(f"   Resposta: {evento_response.text}")
                
            # Buscar todos os eventos
            print("\n4. Listando todos os eventos...")
            all_eventos = requests.get(f"{BASE_URL}/eventos/", headers=headers)
            if all_eventos.status_code == 200:
                eventos = all_eventos.json()
                print(f"✅ Total de eventos: {len(eventos)}")
                for evt in eventos:
                    print(f"   - ID {evt['id']}: {evt['data_evento']} | Status: {evt['status']} | Tipo: {evt.get('tipo', 'N/A')}")
        else:
            print(f"❌ Erro no login: {login_response.status_code}")
            print(f"   Resposta: {login_response.text}")
            print("\n💡 Dica: Verifique se o email/senha estão corretos")
            print("   Ou crie um usuário admin no banco de dados")
    else:
        print(f"Resposta: {response.status_code}")
        print(response.json())
        
except Exception as e:
    print(f"❌ ERRO: {e}")
    print("\n💡 Certifique-se de que o backend está rodando em http://localhost:8000")

print("\n" + "=" * 60)
