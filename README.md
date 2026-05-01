# VideoConf Distribuído com ZeroMQ

![Status](https://img.shields.io/badge/status-completo-brightgreen) ![Python](https://img.shields.io/badge/python-3.8%2B-blue) ![ZeroMQ](https://img.shields.io/badge/zeromq-27.1.0-blue)

Ferramenta de videoconferência distribuída em Python 3 com suporte a **vídeo, áudio e texto** usando **ZeroMQ** como middleware de comunicação.

## Integrantes do Grupo

```
1. Artur Kioshi de Almeida Nacafucasaco (802405)
2. Breno Dias Arantes dos Santos (800577)
3. Leonardo Shoji Ishiy
4. Maykon dos Santos Gonçalves (821653)
5. Renato Dias Ferreira Campos (821328)
```

## Características

- **Múltiplos Brokers Cooperando** - Cluster de brokers em malha (mesh)  
- **Descoberta Automática** - Service discovery via UDP heartbeat  
- **Tolerância a Falhas** - Failover automático entre brokers  
- **QoS Adaptativo** - Diferentes estratégias por tipo de mídia  
- **Concorrência** - 8+ threads para captura/envio/recepção  
- **Salas de Chat** - Isolamento de grupos (geral, sala1, sala2, etc)  
- **Presença Distribuída** - Consulta de usuários online em todos brokers  
- **UI Desktop** - Interface com Tkinter (vídeo em grade 2x2 + chat)

## Requisitos

- **Python 3.8+**
- **pip** (gerenciador de pacotes)
- Câmera USB (opcional para vídeo)
- Microfone/Alto-falantes (opcional para áudio)

## Instalação Rápida

### 1. Clonar/Preparar Repositório
```bash
cd sd-trab1
```

### 2. Criar Ambiente Virtual

python -m venv venv
source venv/bin/activate
```

### 3. Instalar Dependências
```bash
pip install -r requirements.txt
```

## Início Rápido (Demo de 3 Brokers + 2 Clientes)

### Terminal 1 - Broker 1
```bash
python broker.py broker1 5500
```

### Terminal 2 - Broker 2
```bash
python broker.py broker2 5510
```

### Terminal 3 - Broker 3 (opcional)
```bash
python broker.py broker3 5520
```

### Terminal 4 - Cliente 1
```bash
python client.py
# Login UI: user1, sala=geral
```

### Terminal 5 - Cliente 2
```bash
python client.py
# Login UI: user2, sala=geral
```

## Uso da Interface

### Video
- Grade 2x2 com seu próprio stream (canto superior esquerdo)
- Até 3 videos remotos dos demais usuários na sala
- Atualização automática a cada 50ms

### Chat
- Pane direita exibe últimas 30 mensagens
- Digite mensagem e clique "Enviar" ou pressione Enter

### Comandos
| Comando | Descrição |
|---------|-----------|
| `/join salaA` | Trocar para sala A (ex: `/join sala1`) |
| `/who` | Listar usuários online (local + remoto) |
| Mensagem normal | Enviar texto para sala |

## Teste de Failover (Tolerância a Falhas)

### Setup
1. Inicie 2 brokers: `broker1 5500` e `broker2 5510`
2. Conecte 1 cliente ao `broker1`
3. Envie mensagens

### Ativar Failover
1. Finalize o `broker1` (Ctrl+C)
2. Observe o cliente após ~6 segundos:
   - Chat mostra: `[Failover] broker1 indisponivel. Procurando outro...`
   - Chat mostra: `Failover para broker broker2`
   - Cliente reconecta automaticamente


## Arquitetura

**Diagrama de Componentes:**

```
┌─ Broker Cluster ───────────────┐
│  ┌─────────────┐                │
│  │  Broker 1   │ ◄─mesh─►      │
│  │   :5500     │                │
│  ├─────────────┤                │
│  │ Broker 2    │ ◄─mesh─►      │
│  │   :5510     │                │
│  ├─────────────┤                │
│  │ Broker 3    │ ◄─mesh─►      │
│  │   :5520     │                │
│  └─────────────┘                │
└────────────────────────────────┘
   ▲         ▲          ▲
   │         │          │
   │    PUB/SUB     REQ/REP
   │   (media)      (control)
   │         │          │
┌──┴──┐  ┌──┴──┐  ┌──┴──┐
│ C1  │  │ C2  │  │ C3  │
└─────┘  └─────┘  └─────┘
```

## Configuração Avançada

### Trocar Estratégia de Seleção de Broker

Na UI de login, escolha:
- **"Menor latência"** (padrão): Seleciona broker com menor latência calculada via heartbeat
- **"Round-robin"**: Distribui clientes uniformemente entre brokers

### Múltiplos Brokers em Portas Customizadas

```bash
python broker.py brokerA 6000  # porta primária 6000
python broker.py brokerB 6100  # porta primária 6100
python broker.py brokerC 6200  # porta primária 6200
```

## Troubleshooting

| Problema | Solução |
|----------|---------|
| "Nenhum broker encontrado" | Inicie pelo menos 1 broker antes de clientes |
| Sem câmera | Video desativado automaticamente, funciona chat/áudio |
| Sem áudio | PyAudio não instalado (opcional); video/chat funcionam |
| Vídeo pixelado | Normal com internet lenta; qualidade adapta automaticamente |
| Chat lento | Texto usa retry 3x; pode haver atraso se broker estiver ocupado |

## Estrutura de Código

### broker.py
```
DistributedBroker
├── start()                       # Inicia todos os workers
├── _media_channel_worker()       # XSUB/XPUB para video/audio/texto
├── _control_server()             # REP para operações de controle
├── _heartbeat_sender/receiver()  # Descoberta de brokers
├── _mesh_connection_manager()    # Conecta à malha inter-broker
├── _presence_sender/receiver()   # Publica/recebe presença distribuída
└── _handle_control_request()     # Processa login/join/leave/send_text
```

### client.py
```
main()
├── LoginUI.run()                 # Janela de login
├── BrokerDiscovery               # Descobre brokers via UDP
├── connect_to_best_broker()      # Login e seleção de broker
├── heartbeat_monitor()           # Monitora saúde + failover
├── start_workers()               # Inicia threads de media
│   ├── video_capture_worker()    # Lê câmera
│   ├── video_send_worker()       # Publica vídeo
│   ├── video_recv_worker()       # Recebe vídeo
│   ├── audio_capture_worker()    # Lê microfone (opcional)
│   ├── audio_send_worker()       # Publica áudio (opcional)
│   ├── audio_recv_worker()       # Reproduz áudio (opcional)
│   └── text_recv_worker()        # Recebe texto
├── build_ui()                    # UI Tkinter
└── send_text_with_retry()        # Envia texto com 3 tentativas
```

