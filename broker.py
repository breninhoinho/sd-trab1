import zmq
import threading
import time
import json
import socket
import sys
from collections import defaultdict
from datetime import datetime, timedelta

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

class BrokerConfig:
    def __init__(self, broker_id, primary_port):
        self.broker_id = broker_id
        self.primary_port = primary_port
        
        # Portas relativas ao primary_port
        self.router_video = primary_port + 1
        self.dealer_video = primary_port + 2
        self.pubsub_video_pub = primary_port + 3
        self.pubsub_video_sub = primary_port + 4
        
        self.router_audio = primary_port + 11
        self.dealer_audio = primary_port + 12
        self.pubsub_audio_pub = primary_port + 13
        self.pubsub_audio_sub = primary_port + 14
        
        self.router_texto = primary_port + 21
        self.dealer_texto = primary_port + 22
        self.pubsub_texto_pub = primary_port + 23
        self.pubsub_texto_sub = primary_port + 24
        
        # Service Discovery
        self.discovery_port = 6000  # porta fixa para discovery
        self.heartbeat_interval = 2  # segundos
        self.heartbeat_timeout = 6  # segundos


# ─────────────────────────────────────────────────────────────────────────────
# BROKER COM SERVICE DISCOVERY
# ─────────────────────────────────────────────────────────────────────────────

class MultiBroker:
    def __init__(self, broker_id, primary_port):
        self.config = BrokerConfig(broker_id, primary_port)
        self.ctx = zmq.Context()
        
        # Descoberta de outros brokers
        self.other_brokers = {}  # {broker_id: {"port": X, "timestamp": T}}
        self.lock_brokers = threading.Lock()
        
        # Gerenciamento de grupos/salas locais
        self.local_groups = defaultdict(list)  # {sala: [usuarios]}
        self.lock_groups = threading.Lock()
        
        # Socket para comunicação entre brokers (REQ-REP)
        self.broker_req = None
        self.broker_rep = None
        
        print(f"\n✓ Broker {self.config.broker_id} inicializado")
        print(f"  Port primária: {self.config.primary_port}")
    
    def start(self):
        """Inicia todos os threads do broker"""
        # Service discovery
        threading.Thread(target=self._heartbeat_sender, daemon=True).start()
        threading.Thread(target=self._heartbeat_receiver, daemon=True).start()
        threading.Thread(target=self._heartbeat_cleanup, daemon=True).start()
        
        # Proxy ROUTER-DEALER para canais (bloqueia, por isso em threads separadas)
        threading.Thread(target=self._proxy_router_dealer, args=("VIDEO",), daemon=True).start()
        threading.Thread(target=self._proxy_router_dealer, args=("AUDIO",), daemon=True).start()
        threading.Thread(target=self._proxy_router_dealer, args=("TEXTO",), daemon=True).start()
        
        # Proxy PUB-SUB para cada canal (em threads separadas)
        threading.Thread(target=self._proxy_pubsub, args=("VIDEO",), daemon=True).start()
        threading.Thread(target=self._proxy_pubsub, args=("AUDIO",), daemon=True).start()
        threading.Thread(target=self._proxy_pubsub, args=("TEXTO",), daemon=True).start()
        
        # Servidor de roteamento entre brokers
        threading.Thread(target=self._broker_router_server, daemon=True).start()
        
        print(f"  [✓] Service discovery ativo (UDP:{self.config.discovery_port})")
        print(f"  [✓] Proxies ROUTER-DEALER ativas")
        print(f"  [✓] Proxies PUB-SUB ativas")
        print(f"  [✓] Servidor de roteamento entre brokers ativo\n")
    
    # ─────────────────────────────────────────────────────────────────────────
    # SERVICE DISCOVERY (UDP Heartbeat)
    # ─────────────────────────────────────────────────────────────────────────
    
    def _heartbeat_sender(self):
        """Envia heartbeat UDP para descoberta"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        while True:
            time.sleep(self.config.heartbeat_interval)
            
            heartbeat = json.dumps({
                "broker_id": self.config.broker_id,
                "port": self.config.primary_port,
                "timestamp": datetime.now().isoformat()
            }).encode()
            
            try:
                sock.sendto(heartbeat, ("255.255.255.255", self.config.discovery_port))
            except OSError:
                # Em caso de erro, tenta envio unicast também para localhost
                sock.sendto(heartbeat, ("127.0.0.1", self.config.discovery_port))
    
    def _heartbeat_receiver(self):
        """Recebe heartbeats UDP de outros brokers"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.config.discovery_port))
        sock.settimeout(1)
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                msg = json.loads(data.decode())
                
                # Ignora seu próprio heartbeat
                if msg["broker_id"] != self.config.broker_id:
                    with self.lock_brokers:
                        self.other_brokers[msg["broker_id"]] = {
                            "port": msg["port"],
                            "timestamp": datetime.now()
                        }
                        print(f"  [Discovery] Broker {msg['broker_id']} detectado em porta {msg['port']}")
            except socket.timeout:
                pass
            except Exception as e:
                pass
    
    def _heartbeat_cleanup(self):
        """Remove brokers que não enviam heartbeat"""
        while True:
            time.sleep(1)
            now = datetime.now()
            
            with self.lock_brokers:
                dead_brokers = []
                for broker_id, info in list(self.other_brokers.items()):
                    if (now - info["timestamp"]).total_seconds() > self.config.heartbeat_timeout:
                        dead_brokers.append(broker_id)
                
                for broker_id in dead_brokers:
                    del self.other_brokers[broker_id]
                    print(f"  [Cleanup] Broker {broker_id} removido (timeout)")
    
    # ─────────────────────────────────────────────────────────────────────────
    # PROXY ROUTER-DEALER COM ROTEAMENTO ENTRE BROKERS
    # ─────────────────────────────────────────────────────────────────────────
    
    def _proxy_router_dealer(self, channel):
        """Proxy ROUTER-DEALER para requisição-resposta"""
        if channel == "VIDEO":
            porta_router = self.config.router_video
            porta_dealer = self.config.dealer_video
        elif channel == "AUDIO":
            porta_router = self.config.router_audio
            porta_dealer = self.config.dealer_audio
        else:  # TEXTO
            porta_router = self.config.router_texto
            porta_dealer = self.config.dealer_texto
        
        # Frontend: ROUTER recebe de clientes
        frontend = self.ctx.socket(zmq.ROUTER)
        frontend.bind(f"tcp://*:{porta_router}")
        
        # Backend: DEALER distribui para workers
        backend = self.ctx.socket(zmq.DEALER)
        backend.bind(f"tcp://*:{porta_dealer}")
        
        print(f"  [{channel} REQ-REP] ROUTER={porta_router} DEALER={porta_dealer}")
        
        # Proxy padrão entre ROUTER-DEALER
        zmq.proxy(frontend, backend)
    
    def _proxy_pubsub(self, channel):
        """Proxy PUB-SUB para broadcast"""
        if channel == "VIDEO":
            porta_pubsub_pub = self.config.pubsub_video_pub
            porta_pubsub_sub = self.config.pubsub_video_sub
        elif channel == "AUDIO":
            porta_pubsub_pub = self.config.pubsub_audio_pub
            porta_pubsub_sub = self.config.pubsub_audio_sub
        else:  # TEXTO
            porta_pubsub_pub = self.config.pubsub_texto_pub
            porta_pubsub_sub = self.config.pubsub_texto_sub
        
        # XSUB recebe PUB
        sub_input = self.ctx.socket(zmq.XSUB)
        sub_input.bind(f"tcp://*:{porta_pubsub_pub}")
        
        # XPUB publica SUB
        pub_output = self.ctx.socket(zmq.XPUB)
        pub_output.bind(f"tcp://*:{porta_pubsub_sub}")
        pub_output.setsockopt(zmq.XPUB_VERBOSE, 1)
        
        print(f"  [{channel} PUB-SUB] PUB={porta_pubsub_pub} SUB={porta_pubsub_sub}")
        
        # Proxy PUB-SUB
        zmq.proxy(sub_input, pub_output)
    
    def _broker_router_server(self):
        """Servidor para receber mensagens de brokers vizinhos"""
        sock = self.ctx.socket(zmq.REP)
        sock.bind(f"tcp://*:{self.config.primary_port + 100}")
        
        while True:
            try:
                msg = sock.recv_json()
                
                # Processa mensagem inter-broker
                resposta = self._processar_mensagem_inter_broker(msg)
                sock.send_json(resposta)
            except Exception as e:
                pass
    
    def _processar_mensagem_inter_broker(self, msg):
        """Processa mensagem vinda de outro broker"""
        msg_type = msg.get("tipo")
        sala = msg.get("sala")
        usuario = msg.get("usuario")
        origem_broker = msg.get("origem_broker")
        visitados = msg.get("visitados", [])
        
        # Evita loops: se mensagem já veio daqui, bloqueia
        if self.config.broker_id in visitados:
            return {"status": "bloqueado", "motivo": "loop_detectado"}
        
        # Se a sala é gerenciada localmente, roteia para os usuários
        with self.lock_groups:
            usuarios_sala = self.local_groups.get(sala, [])
        
        if usuarios_sala:
            # Há usuários desta sala aqui - entreg local
            return {"status": "roteado_local", "usuarios": usuarios_sala, "count": len(usuarios_sala)}
        
        # Marca que passou por aqui e roteia para outros brokers
        visitados_novos = visitados + [self.config.broker_id]
        msg_novo = dict(msg)
        msg_novo["visitados"] = visitados_novos
        
        # Roteia para brokers vizinhos (exceto onde veio e já visitados)
        self._rotear_para_brokers_vizinhos(msg_novo)
        return {"status": "reencaminhado", "para_brokers": len(self.other_brokers)}
    
    def _rotear_para_brokers_vizinhos(self, msg):
        """Envia mensagem para brokers vizinhos (exceto origem e visitados)"""
        visitados = msg.get("visitados", [])
        
        with self.lock_brokers:
            brokers = [
                (bid, info) for bid, info in self.other_brokers.items()
                if bid not in visitados
            ]
        
        for broker_id, info in brokers:
            try:
                cliente = self.ctx.socket(zmq.REQ)
                cliente.connect(f"tcp://localhost:{info['port'] + 100}")
                cliente.setsockopt(zmq.RCVTIMEO, 500)  # Mais rápido
                
                cliente.send_json(msg)
                cliente.recv_json()
                cliente.close()
            except Exception as e:
                pass
    
    def registrar_usuario(self, sala, usuario):
        """Registra usuário em uma sala (gerenciada localmente)"""
        with self.lock_groups:
            if usuario not in self.local_groups[sala]:
                self.local_groups[sala].append(usuario)
                print(f"  [Grupo] {usuario} entrou em {sala}")
    
    def remover_usuario(self, sala, usuario):
        """Remove usuário de uma sala"""
        with self.lock_groups:
            if sala in self.local_groups and usuario in self.local_groups[sala]:
                self.local_groups[sala].remove(usuario)
                print(f"  [Grupo] {usuario} saiu de {sala}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python broker.py <broker_id> <primary_port>")
        print("Exemplo: python broker.py broker1 5500")
        sys.exit(1)
    
    broker_id = sys.argv[1]
    try:
        primary_port = int(sys.argv[2])
    except ValueError:
        print("Erro: primary_port deve ser um número inteiro")
        sys.exit(1)
    
    broker = MultiBroker(broker_id, primary_port)
    broker.start()
    
    print("Broker rodando. Ctrl+C para parar.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nBroker encerrado.")


