# VideoConf - Arquitetura Multi-Broker com Service Discovery

## Arquitetura

Sistema de videoconferência distribuído com múltiplos brokers que se descobrem via UDP heartbeat. Cada broker gerencia um subconjunto de usuários/grupos e roteia mensagens inteligentemente evitando loops.

### Componentes

1. **Brokers**: Instâncias independentes com diferentes portas
   - Service discovery via UDP heartbeat (porta fixa 6000)
   - ROUTER-DEALER para cada canal (vídeo, áudio, texto)
   - Roteamento inteligente entre brokers
   - Gerenciamento de grupos/salas locais

2. **Clientes**: Conectam a um broker específico
   - Enviam sala/grupo em cada mensagem
   - Registram-se no broker ao entrar
   - Recebem dados via PUB-SUB broadcast

## Como Usar

### 1. Inicie múltiplos brokers

```bash
# Terminal 1 - Broker 1 (porta primária 5500)
python broker.py broker1 5500

# Terminal 2 - Broker 2 (porta primária 5600)
python broker.py broker2 5600

# Terminal 3 - Broker 3 (porta primária 5700)
python broker.py broker3 5700
```

### 2. Inicie clientes conectando a diferentes brokers

```bash
# Terminal 4 - Cliente no Broker1
python client.py 

# Terminal 5 - Cliente no Broker2
python client.py 

# Terminal 6 - Outro cliente no Broker1
python client.py 
```

## Estrutura de Portas

Para cada broker com `primary_port = P`:

### VÍDEO
- ROUTER (cliente → broker): `P + 1`
- DEALER (distribuição interna): `P + 2`
- XSUB (recebe PUB): `P + 3`
- XPUB (publica SUB): `P + 4`

### ÁUDIO
- ROUTER: `P + 11`
- DEALER: `P + 12`
- XSUB: `P + 13`
- XPUB: `P + 14`

### TEXTO
- ROUTER: `P + 21`
- DEALER: `P + 22`
- XSUB: `P + 23`
- XPUB: `P + 24`

### Service Discovery
- UDP Broadcast: Porta `6000` (fixa em todos os brokers)

### Inter-Broker Communication
- REP Server: `P + 100` (roteamento entre brokers)

## Fluxo de Mensagens

### Publish (Vídeo/Áudio/Texto)
```
Cliente A (sala: "geral")
    ↓
    ├→ REQ para ROUTER (notificação)
    └→ PUB para XSUB (dados)
         ↓
         Broker (gerencia sala "geral")
         ↓
         XPUB → SUB clientes da sala
```

### Roteamento Inter-Broker
```
Cliente A no Broker1 (sala: "geral")
    ↓
Broker1 (sala "geral" não está aqui)
    ↓
    Envia para Broker2 e Broker3
    ↓
Broker2 tem sala "geral"
    ↓
    Roteia para Cliente B
```

### Prevenção de Loops
```
Broker1 recebe mensagem com origem_broker = "Broker1"
    ↓
    Bloqueia reencaminhamento (já veio daqui)
    ↓
    Apenas roteia para clientes locais
```

## Protocolo de Mensagens

### Registrar Usuário
```json
{
    "tipo": "registrar",
    "usuario": "joão",
    "sala": "geral",
    "broker_id": "broker1"
}
```

### Frame (Vídeo/Áudio/Texto)
```json
{
    "tipo": "frame",
    "stream": "video|audio|texto",
    "sala": "geral",
    "usuario": "joão",
    "broker_origem": "broker1",
    "timestamp": 1234567890.123,
    "msg": "..."  // apenas para texto
}
```

### Roteamento Inter-Broker
```json
{
    "tipo": "frame",
    "stream": "video",
    "sala": "geral",
    "usuario": "joão",
    "broker_origem": "broker1",  // Marca origem para evitar loops
    "timestamp": 1234567890.123
}
```

## Service Discovery (Heartbeat)

**Intervalo**: 2 segundos
**Timeout**: 6 segundos (3 heartbeats perdidos)

Formato do heartbeat UDP:
```json
{
    "broker_id": "broker1",
    "port": 5500,
    "timestamp": "2026-04-22T10:30:45.123456"
}
```

## Vantagens da Arquitetura

✅ **Escalabilidade**: Adicione brokers dinamicamente
✅ **Resiliência**: Brokers descobrem uns aos outros automaticamente
✅ **Distribuição de Carga**: ROUTER-DEALER com load balancing
✅ **Prevenção de Loops**: Marca origem das mensagens
✅ **Gerenciamento de Grupos**: Cada broker gerencia subconjunto de salas
✅ **Broadcast Eficiente**: PUB-SUB para dados em tempo real

## Requisitos

- Python 3.8+
- ZMQ (pyzmq)
- OpenCV (cv2)
- Tkinter
- PIL/Pillow
- PyAudio (opcional, para áudio)

## Instalação

```bash
pip install pyzmq opencv-python pillow
# Opcional: pip install pyaudio
```

## Troubleshooting

### Broker não descobre outros brokers
- Verifique se está usando localhost ou mesmo IP
- Confirme que UDP porta 6000 não está bloqueada

### Cliente não conecta ao broker
- Confirme que o broker_port está correto
- Verifique se o broker está rodando com aquela porta primária

### Mensagens não chegam entre brokers
- Verifique a sala/grupo nas mensagens
- Confirme que os brokers conseguem se comunicar na porta 6000

