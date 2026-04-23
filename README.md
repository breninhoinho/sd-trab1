# VideoConf Distribuido com ZeroMQ

Projeto de videoconferencia (video, audio e texto) em Python3 com arquitetura distribuida baseada em ZeroMQ.

## Objetivo da evolucao

Esta versao implementa:

- multiplos brokers cooperando
- descoberta dinamica de brokers (service discovery)
- tolerancia a falhas com failover automatico
- QoS simplificado por tipo de midia
- concorrencia com threads separadas
- identidade, sessao, presenca e salas

## Arquitetura

### 1) Cluster de brokers

Cada broker executa de forma independente e publica heartbeat por UDP.

- descoberta: UDP porta `6000`
- plano de dados cliente/broker por canal (XSUB/XPUB):
  - video: `P+3` (pub_in), `P+4` (sub_out)
  - audio: `P+13` (pub_in), `P+14` (sub_out)
  - texto: `P+23` (pub_in), `P+24` (sub_out)
- plano de controle (REQ/REP): `P+200`
- malha inter-broker (PUB/SUB): `P+300`

### 2) Roteamento inter-broker e anti-loop

Mensagens de midia recebidas localmente sao:

1. entregues aos assinantes locais
2. reenviadas para outros brokers via malha

Cada relay inclui metadados com:

- `msg_id` unico
- `origin_broker`
- `ttl`

Loop e duplicacao sao evitados por cache de mensagens ja vistas + TTL decremental.

### 3) Service discovery

Cliente nao precisa conhecer broker fixo.

- brokers se anunciam por heartbeat UDP
- cliente escolhe broker por:
  - menor latencia
  - round-robin

### 4) Tolerancia a falhas

Cliente possui monitor de heartbeat (ping no controle):

- se broker falha por 3 tentativas consecutivas
- cliente faz failover automatico para outro broker descoberto
- sessao e sala sao restabelecidas no novo broker

### 5) QoS simplificado

- Texto (garantia de entrega): envio via plano de controle com `text_id` + retry ate 3 tentativas no cliente
- Audio (baixa latencia): buffer pequeno com drop de chunks antigos quando fila enche
- Video (taxa adaptativa): ajuste de qualidade JPEG conforme backlog e drop de frames antigos no buffer

### 6) Concorrencia (threads)

Cliente separa explicitamente:

- captura de video
- envio de video
- recepcao de video
- captura de audio
- envio de audio
- recepcao de audio
- recepcao de texto
- monitoramento de heartbeat/failover
- renderizacao (loop UI)

### 7) Identidade, sessao, presenca e salas

- login simples com `user_id` unico
- entrada em sala no login
- troca de sala em runtime (`/join salaX`)
- consulta de presenca (`/who`)

## Requisitos

- Python 3.8+
- pyzmq
- numpy
- opencv-python
- pillow
- pyaudio (opcional para audio)

Instalar dependencias:

```bash
pip install -r requirements.txt
```

## Execucao

### 1) Iniciar brokers

Exemplo com 3 brokers:

```bash
python broker.py broker1 5500
python broker.py broker2 5600
python broker.py broker3 5700
```

### 2) Iniciar clientes

```bash
python client.py
```

No login, escolha:

- `user_id`
- sala inicial
- estrategia de selecao de broker

## Comandos no chat

- enviar mensagem: texto normal
- trocar sala: `/join nome_da_sala`
- listar presenca local/salas: `/who`

## Mapeamento para os requisitos do enunciado

1. Arquitetura distribuida com multiplos brokers: implementado em `broker.py` com descoberta + malha inter-broker
2. Service discovery: heartbeats UDP + selecao de broker no cliente
3. Tolerancia a falhas: ping + timeout + failover automatico
4. QoS simplificado: retry texto, drop audio, adaptacao e drop video
5. Concorrencia e processamento assincrono: threads dedicadas por etapa
6. Identidade e sessao: login unico, presenca, entrada/saida de salas

## Observacoes

- Audio exige `PyAudio`; sem ele o cliente funciona com video/texto.
- Em redes locais restritas, broadcast UDP pode ser bloqueado; para teste local, execute tudo no mesmo host.
