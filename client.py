import sys
import zmq
import cv2
import threading
import numpy as np
import json
import time
import tkinter as tk
from tkinter import font as tkfont
import socket
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

class ClientConfig:
    def __init__(self, broker_id, broker_port):
        self.broker_id = broker_id
        self.broker_port = broker_port
        
        # Portas relativas ao broker_port
        self.router_video = broker_port + 1
        self.pubsub_video_sub = broker_port + 4
        
        self.router_audio = broker_port + 11
        self.pubsub_audio_sub = broker_port + 14
        
        self.router_texto = broker_port + 21
        self.pubsub_texto_pub = broker_port + 23 
        self.pubsub_texto_sub = broker_port + 24


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE DISCOVERY (Igual aos brokers, mas para cliente)
# ─────────────────────────────────────────────────────────────────────────────

class BrokerDiscovery:
    """Descobre automaticamente brokers disponíveis via UDP heartbeat"""
    
    def __init__(self):
        self.available_brokers = {}  # {broker_id: {"port": X, "timestamp": T, "latency": ms}}
        self.lock = threading.Lock()
        self.round_robin_index = 0
        self.discovery_port = 6000
        self.heartbeat_timeout = 6  # segundos
        self.running = True
        
        # Inicia threads de descoberta
        threading.Thread(target=self._listen_heartbeats, daemon=True).start()
        threading.Thread(target=self._cleanup_dead_brokers, daemon=True).start()
    
    def _listen_heartbeats(self):
        """Escuta heartbeats UDP de brokers"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.discovery_port))
        sock.settimeout(1)
        
        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                msg = json.loads(data.decode())
                
                # Calcula latência (ping)
                broker_timestamp = datetime.fromisoformat(msg["timestamp"])
                latency_ms = (datetime.now() - broker_timestamp).total_seconds() * 1000
                
                broker_id = msg["broker_id"]
                port = msg["port"]
                
                with self.lock:
                    self.available_brokers[broker_id] = {
                        "port": port,
                        "timestamp": datetime.now(),
                        "latency": latency_ms
                    }
                    
                    # Log apenas na primeira descoberta
                    if broker_id not in self.available_brokers or latency_ms < 50:
                        print(f"  [Discovery] Broker {broker_id} em porta {port} (latência: {latency_ms:.1f}ms)")
            
            except socket.timeout:
                pass
            except Exception as e:
                pass
    
    def _cleanup_dead_brokers(self):
        """Remove brokers que não enviam heartbeat"""
        while self.running:
            time.sleep(1)
            now = datetime.now()
            
            with self.lock:
                dead_brokers = []
                for broker_id, info in list(self.available_brokers.items()):
                    if (now - info["timestamp"]).total_seconds() > self.heartbeat_timeout:
                        dead_brokers.append(broker_id)
                
                for broker_id in dead_brokers:
                    del self.available_brokers[broker_id]
                    print(f"  [Cleanup] Broker {broker_id} removido (offline)")
    
    def get_best_broker_round_robin(self):
        """Retorna próximo broker usando round-robin"""
        with self.lock:
            if not self.available_brokers:
                return None, None
            
            brokers = list(self.available_brokers.items())
            self.round_robin_index = (self.round_robin_index + 1) % len(brokers)
            broker_id, info = brokers[self.round_robin_index]
            
            return broker_id, info["port"]
    
    def get_best_broker_lowest_latency(self):
        """Retorna broker com menor latência"""
        with self.lock:
            if not self.available_brokers:
                return None, None
            
            best_broker = min(
                self.available_brokers.items(),
                key=lambda x: x[1]["latency"]
            )
            broker_id, info = best_broker
            return broker_id, info["port"]
    
    def get_available_brokers(self):
        """Retorna lista de todos os brokers disponíveis"""
        with self.lock:
            return dict(self.available_brokers)
    
    def stop(self):
        """Para a descoberta"""
        self.running = False


# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL STATE
# ─────────────────────────────────────────────────────────────────────────────

BROKER = "localhost"
BROKER_ID = None  # Descoberto automaticamente
BROKER_PORT = None  # Descoberto automaticamente
config = None
broker_discovery = BrokerDiscovery()

ctx = zmq.Context()
frames_remotos = {}
chat = []
lock = threading.Lock()
NOME = ""
SALA = ""
pub_texto = None
req_video = None
req_audio = None
req_texto = None


def tela_entrada():
    root = tk.Tk()
    root.title("VideoConf")
    root.geometry("360x320")
    root.configure(bg="#121212")

    tk.Label(root, text="VideoConf",
             fg="white", bg="#121212",
             font=("Segoe UI", 18, "bold")).pack(pady=20)

    nome = tk.Entry(root, font=("Segoe UI", 12))
    nome.pack(pady=10, ipadx=10, ipady=6)

    sala = tk.Entry(root, font=("Segoe UI", 12))
    sala.insert(0, "geral")
    sala.pack(pady=10, ipadx=10, ipady=6)

    result = {}

    def entrar():
        result["nome"] = nome.get()
        result["sala"] = sala.get()
        root.destroy()

    tk.Button(root, text="Entrar",
              command=entrar,
              bg="#3a7cff",
              fg="white",
              relief="flat").pack(pady=20, ipadx=10, ipady=6)

    root.mainloop()

    return result["nome"], result["sala"]

# ─────────────────────────────────────────────────────────────────────────────
# THREADS DE REDE
# ─────────────────────────────────────────────────────────────────────────────

def publica_video():
    global req_video
    
    # Conecta ao ROUTER (requisição-resposta)
    req_video = ctx.socket(zmq.REQ)
    req_video.connect(f"tcp://{BROKER}:{config.router_video}")
    req_video.setsockopt(zmq.RCVTIMEO, 500)  # timeout de 500ms
    
    # Conecta ao canal PUB-SUB broadcast
    pub = ctx.socket(zmq.PUB)
    pub.connect(f"tcp://{BROKER}:{config.router_video - 1}")  # PUBSUB_VIDEO_PUB
    time.sleep(0.3)

    cam = cv2.VideoCapture(0)
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

    while True:
        ok, frame = cam.read()
        if not ok:
            continue
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
        
        # tópico inclui a sala → clientes filtram só a sala deles
        topico = f"video:{SALA}:{NOME}".encode()
        
        # Envia pelo canal PUB-SUB broadcast
        pub.send_multipart([topico, buf.tobytes()])
        
        # Notifica via ROUTER com informações da sala
        try:
            req_video.send_json({
                "tipo": "frame",
                "stream": "video",
                "sala": SALA,
                "usuario": NOME,
                "broker_origem": BROKER_ID,
                "origem_broker": BROKER_ID,
                "visitados": [BROKER_ID],
                "timestamp": time.time()
            })
            req_video.recv_json()
        except zmq.error.Again:
            pass  # Timeout, continua
        
        time.sleep(1 / 15)


def recebe_video():
    sub = ctx.socket(zmq.SUB)
    sub.connect(f"tcp://{BROKER}:{config.pubsub_video_sub}")
    sub.setsockopt(zmq.SUBSCRIBE, f"video:{SALA}:".encode())

    while True:
        topico, dados = sub.recv_multipart()
        remetente = topico.decode().split(":")[2]
        if remetente == NOME:
            continue
        arr   = np.frombuffer(dados, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is not None:
            with lock:
                frames_remotos[remetente] = frame


def publica_audio():
    global req_audio
    
    try:
        import pyaudio
    except ImportError:
        return

    # Conecta ao ROUTER (requisição-resposta)
    req_audio = ctx.socket(zmq.REQ)
    req_audio.connect(f"tcp://{BROKER}:{config.router_audio}")
    req_audio.setsockopt(zmq.RCVTIMEO, 500)
    
    # Conecta ao canal PUB-SUB broadcast
    pub = ctx.socket(zmq.PUB)
    pub.connect(f"tcp://{BROKER}:{config.router_audio - 1}")  # PUBSUB_AUDIO_PUB
    time.sleep(0.3)

    pa     = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1,
                     rate=44100, input=True, frames_per_buffer=1024)
    
    while True:
        dados = stream.read(1024, exception_on_overflow=False)
        pub.send_multipart([f"audio:{SALA}:{NOME}".encode(), dados])
        
        # Notifica via ROUTER
        try:
            req_audio.send_json({
                "tipo": "frame",
                "stream": "audio",
                "sala": SALA,
                "usuario": NOME,
                "broker_origem": BROKER_ID,
                "origem_broker": BROKER_ID,
                "visitados": [BROKER_ID]
            })
            req_audio.recv_json()
        except zmq.error.Again:
            pass


def recebe_audio():
    try:
        import pyaudio
    except ImportError:
        return

    sub = ctx.socket(zmq.SUB)
    sub.connect(f"tcp://{BROKER}:{config.pubsub_audio_sub}")
    sub.setsockopt(zmq.SUBSCRIBE, f"audio:{SALA}:".encode())

    pa     = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1,
                     rate=44100, output=True, frames_per_buffer=1024)
    while True:
        topico, dados = sub.recv_multipart()
        remetente = topico.decode().split(":")[2]
        if remetente != NOME:
            stream.write(dados)


def recebe_texto():
    sub = ctx.socket(zmq.SUB)
    sub.connect(f"tcp://{BROKER}:{config.pubsub_texto_sub}")
    sub.setsockopt(zmq.SUBSCRIBE, f"texto:{SALA}:".encode())

    while True:
        _, dados = sub.recv_multipart()
        msg = json.loads(dados)
        if msg["de"] != NOME:
            with lock:
                ts = time.strftime("%H:%M")
                chat.append({"de": msg["de"], "msg": msg["msg"], "ts": ts})
                if len(chat) > 200:
                    chat.pop(0)


def envia_texto(mensagem):
    global pub_texto, req_texto
    
    payload = json.dumps({"de": NOME, "msg": mensagem}).encode()
    pub_texto.send_multipart([f"texto:{SALA}:{NOME}".encode(), payload])
    
    # Notifica via ROUTER
    try:
        req_texto.send_json({
            "tipo": "mensagem",
            "stream": "texto",
            "sala": SALA,
            "usuario": NOME,
            "msg": mensagem,
            "broker_origem": BROKER_ID,
            "origem_broker": BROKER_ID,
            "visitados": [BROKER_ID]
        })
        req_texto.recv_json()
    except zmq.error.Again:
        pass
    
    with lock:
        ts = time.strftime("%H:%M")
        chat.append({"de": NOME, "msg": mensagem, "ts": ts})

import tkinter as tk
from tkinter import scrolledtext

class ChatUI:
    def __init__(self, root):
        self.frame = tk.Frame(root, bg="#1e1e1e")
        self.frame.pack(side="right", fill="y")

        self.chat_box = scrolledtext.ScrolledText(
            self.frame,
            wrap=tk.WORD,
            width=40,
            height=25,
            bg="#2b2b2b",
            fg="white",
            insertbackground="white"
        )
        self.chat_box.pack(padx=10, pady=10)
        self.chat_box.config(state="disabled")

        self.entry = tk.Entry(
            self.frame,
            bg="#333",
            fg="white",
            insertbackground="white"
        )
        self.entry.pack(fill="x", padx=10, pady=5)

        self.btn = tk.Button(self.frame, text="Enviar", command=self.enviar)
        self.btn.pack(pady=5)

    def adicionar_msg(self, nome, msg, eu=False):
        self.chat_box.config(state="normal")

        prefixo = "Você" if eu else nome
        self.chat_box.insert(tk.END, f"{prefixo}: {msg}\n")

        self.chat_box.config(state="disabled")
        self.chat_box.yview(tk.END)

    def enviar(self):
        texto = self.entry.get().strip()
        if texto:
            envia_texto(texto)  # sua função ZMQ
            self.entry.delete(0, tk.END)

from PIL import Image, ImageTk
import cv2

class VideoUI:
    def __init__(self, root):
        self.label = tk.Label(root)
        self.label.pack(side="left")

    def atualizar(self, frame):
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        img = Image.fromarray(frame)
        imgtk = ImageTk.PhotoImage(image=img)

        self.label.imgtk = imgtk
        self.label.configure(image=imgtk)

import threading
import time

def sala_principal():
    global pub_texto, req_texto, BROKER_ID, BROKER_PORT

    # =========================
    # ZMQ
    # =========================
    # Socket REQ para se comunicar com ROUTER (texto)
    req_texto = ctx.socket(zmq.REQ)
    req_texto.connect(f"tcp://{BROKER}:{config.router_texto}")
    req_texto.setsockopt(zmq.RCVTIMEO, 500)
    
    # Socket PUB para broadcast de texto
    pub_texto = ctx.socket(zmq.PUB)
    pub_texto.connect(f"tcp://{BROKER}:{config.pubsub_texto_pub}")
    time.sleep(0.3)

    # Registra usuário no broker
    try:
        req_registro = ctx.socket(zmq.REQ)
        req_registro.connect(f"tcp://{BROKER}:{config.broker_port + 100}")
        req_registro.setsockopt(zmq.RCVTIMEO, 1000)
        req_registro.send_json({
            "tipo": "registrar",
            "usuario": NOME,
            "sala": SALA,
            "broker_id": BROKER_ID
        })
        resp = req_registro.recv_json()
        print(f"Registrado no broker: {resp}")
        req_registro.close()
    except Exception as e:
        print(f"Erro ao registrar: {e}")

    for fn in [publica_video, recebe_video, publica_audio, recebe_audio, recebe_texto]:
        threading.Thread(target=fn, daemon=True).start()

    # =========================
    # Tkinter
    # =========================
    root = tk.Tk()
    root.title(f"VideoConf — {NOME} @ {SALA}")
    root.geometry("1000x600")

    video_ui = VideoUI(root)
    chat_ui = ChatUI(root)

    # =========================
    # Câmera
    # =========================
    cam = cv2.VideoCapture(0)

    def loop():
        ok, frame = cam.read()
        if not ok:
            frame = np.zeros((240, 320, 3), np.uint8)

        # pega dados compartilhados
        with lock:
            remotos = dict(frames_remotos)
            historico = list(chat)

        # (simplificação: mostra só câmera local)
        video_ui.atualizar(frame)

        # atualiza chat
        chat_ui.chat_box.config(state="normal")
        chat_ui.chat_box.delete(1.0, tk.END)

        for msg in historico[-20:]:
            eh_eu = msg["de"] == NOME
            nome = "Você" if eh_eu else msg["de"]
            chat_ui.chat_box.insert(tk.END, f"{nome}: {msg['msg']}\n")

        chat_ui.chat_box.config(state="disabled")

        # loop a cada 30ms
        root.after(30, loop)

    loop()
    root.mainloop()

    cam.release()

if __name__ == "__main__":
    print("=" * 70)
    print("  VIDEOCONF - CLIENTE COM AUTO-DISCOVERY")
    print("=" * 70)
    print()
    
    # Aguarda descoberta de brokers (máximo 5 segundos)
    print("[*] Descobrindo brokers disponíveis via UDP...")
    for i in range(50):  # 5 segundos com timeout de 100ms
        time.sleep(0.1)
        brokers = broker_discovery.get_available_brokers()
        if brokers:
            break
    
    brokers = broker_discovery.get_available_brokers()
    
    if not brokers:
        print("\n[✗] Nenhum broker disponível!")
        print("    Certifique-se de que pelo menos um broker está rodando:")
        print("    python broker.py broker1 5500")
        sys.exit(1)
    
    print(f"\n[✓] Encontrados {len(brokers)} brokers:")
    for bid, info in brokers.items():
        print(f"    - {bid}: porta {info['port']} (latência: {info['latency']:.1f}ms)")
    
    # Seleciona broker usando round-robin
    BROKER_ID, BROKER_PORT = broker_discovery.get_best_broker_round_robin()
    print(f"\n[→] Conectando ao broker {BROKER_ID} na porta {BROKER_PORT} (round-robin)")
    
    config = ClientConfig(BROKER_ID, BROKER_PORT)
    
    print()
    NOME, SALA = tela_entrada()
    sala_principal()
