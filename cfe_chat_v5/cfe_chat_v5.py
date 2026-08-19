#!/usr/bin/env python3
"""
CFE-Chat v.5 — Decentralized P2P LAN Chat
Features:
  - Shared room + private DMs
  - File transfer with progress
  - Persistent history & contacts (only people you chatted with)
  - Sound + title flash on new message
  - Right-click copy (message / IP)
  - Typing indicator
  - Connection quality (RTT)
  - Optional shared-secret encryption (Fernet)
  - Paste image from clipboard
  - System tray (optional, if pystray available)
  - Online (green) / Offline (red) only — no Away/Busy
"""

import socket
import threading
import os
import sys
import time
import base64
import hashlib
import io
from datetime import datetime
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, colorchooser
import webbrowser
import struct
import json
from pathlib import Path
import shutil
import logging
from concurrent.futures import ThreadPoolExecutor
import uuid
import platform

if sys.version_info < (3, 8):
    print("Python 3.8+ required")
    sys.exit(1)

if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
    print("CFE-Chat v.5 — Decentralized P2P LAN Chat")
    print("Usage: python3 cfe_chat_v5.py")
    sys.exit(0)

try:
    import customtkinter as ctk
except ImportError as exc:
    raise SystemExit(
        "CustomTkinter required.\n  python -m pip install customtkinter"
    ) from exc

# Optional deps
HAS_CRYPTO = False
try:
    from cryptography.fernet import Fernet, InvalidToken
    HAS_CRYPTO = True
except ImportError:
    pass

HAS_PIL = False
try:
    from PIL import Image, ImageGrab, ImageTk
    HAS_PIL = True
except ImportError:
    pass

HAS_TRAY = False
try:
    import pystray
    from pystray import MenuItem as TrayMenuItem
    HAS_TRAY = True
except ImportError:
    pass

# ─── Constants ────────────────────────────────────────────────────────────────
PORT = 2222
BROADCAST_PORT = 2223
LOG_FILE = "log.txt"
BUFFER_SIZE = 65536
TG_CHANNEL_URL = "https://t.me/CFE_Chat"
FILE_CHUNK_SIZE = 64 * 1024
DOWNLOADS_FOLDER = str(Path.home() / "Downloads")
DATA_DIR = "chat_data"
DISCOVERY_INTERVAL = 2.5
MAX_RECONNECT_ATTEMPTS = 4
SOCKET_TIMEOUT = 15
VERSION = "v.5"
MAX_MESSAGES_UI = 300
MAX_HEADER_SIZE = 512 * 1024
PING_INTERVAL = 10
HISTORY_LIMIT = 500  # per conversation

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.ERROR)

# ─── Global state ─────────────────────────────────────────────────────────────
nickname = None
connections = {}
connection_lock = threading.Lock()
message_queue = queue.Queue()
stop_event = threading.Event()
all_files = {}
all_files_lock = threading.Lock()
connected_peers = {}       # ip -> nickname (currently online)
peers_lock = threading.Lock()
known_peers = set()
known_peers_lock = threading.Lock()
peer_rtt = {}              # ip -> ms
peer_rtt_lock = threading.Lock()
# Contacts you actually chatted with (persisted)
saved_contacts = {}        # ip -> {"nickname": str, "last_seen": str}
saved_contacts_lock = threading.Lock()
thread_pool = ThreadPoolExecutor(max_workers=14)

# Encryption (optional shared secret)
fernet = None  # Fernet instance or None

# ─── Paths ────────────────────────────────────────────────────────────────────
def get_data_dir():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, DATA_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def get_log_path():
    return os.path.join(get_data_dir(), LOG_FILE)


def get_received_dir():
    path = os.path.join(get_data_dir(), "received_files")
    os.makedirs(path, exist_ok=True)
    return path


def get_history_path():
    return os.path.join(get_data_dir(), "history.json")


def get_contacts_path():
    return os.path.join(get_data_dir(), "contacts.json")


def setup_logging():
    logging.basicConfig(
        filename=os.path.join(get_data_dir(), "error.log"),
        level=logging.ERROR,
        format="%(asctime)s - %(levelname)s - %(message)s",
        force=True,
    )


def ensure_log_file():
    path = get_log_path()
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
    return path


def load_nickname():
    try:
        with open(get_log_path(), "r", encoding="utf-8") as f:
            first = f.readline().strip()
            if first:
                return first
    except OSError:
        pass
    return None


def save_nickname(name):
    path = get_log_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        lines = []
    if lines:
        lines[0] = name + "\n"
    else:
        lines = [name + "\n"]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def write_to_log(text):
    try:
        ts = datetime.now().strftime("%d.%m.%Y %H:%M")
        with open(get_log_path(), "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {text}\n")
    except OSError:
        pass


# ─── Contacts persistence (only people you talked to) ─────────────────────────
def load_contacts():
    global saved_contacts
    try:
        with open(get_contacts_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                with saved_contacts_lock:
                    saved_contacts = data
    except (OSError, json.JSONDecodeError):
        pass


def save_contacts():
    try:
        with saved_contacts_lock:
            data = dict(saved_contacts)
        with open(get_contacts_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def remember_contact(ip, nick):
    """Call when you exchange a real message with someone."""
    with saved_contacts_lock:
        saved_contacts[ip] = {
            "nickname": nick,
            "last_seen": datetime.now().strftime("%d.%m.%Y %H:%M"),
        }
    save_contacts()


# ─── History persistence ──────────────────────────────────────────────────────
def load_all_history():
    try:
        with open(get_history_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_all_history(history_dict):
    try:
        # Trim each conversation
        trimmed = {}
        for key, msgs in history_dict.items():
            trimmed[key] = msgs[-HISTORY_LIMIT:]
        with open(get_history_path(), "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=0)
    except OSError:
        pass


# ─── Encryption helpers ───────────────────────────────────────────────────────
def derive_fernet(password: str):
    if not HAS_CRYPTO or not password:
        return None
    # Deterministic key from password
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_text(text: str) -> str:
    if fernet is None:
        return text
    try:
        return fernet.encrypt(text.encode("utf-8")).decode("ascii")
    except Exception:
        return text


def decrypt_text(text: str) -> str:
    if fernet is None:
        return text
    try:
        return fernet.decrypt(text.encode("ascii")).decode("utf-8")
    except Exception:
        return text  # not encrypted or wrong key


# ─── Network framing ──────────────────────────────────────────────────────────
def is_socket_alive(sock):
    try:
        sock.settimeout(0.0)
        data = sock.recv(1, socket.MSG_PEEK)
        return True
    except (BlockingIOError, InterruptedError):
        return True
    except (OSError, socket.error):
        return False
    finally:
        try:
            sock.settimeout(SOCKET_TIMEOUT)
        except OSError:
            pass


def sendall_with_retry(sock, data, max_retries=3):
    for attempt in range(max_retries):
        try:
            sock.sendall(data)
            return True
        except (socket.error, BrokenPipeError, ConnectionResetError, OSError):
            if attempt == max_retries - 1:
                return False
            time.sleep(0.08 * (attempt + 1))
    return False


def send_frame(conn, header_dict):
    try:
        payload = json.dumps(header_dict, ensure_ascii=False).encode("utf-8")
        if len(payload) > MAX_HEADER_SIZE:
            return False
        header_len = struct.pack("!I", len(payload))
        return sendall_with_retry(conn, header_len + payload)
    except (TypeError, ValueError, OSError):
        return False


def recv_exact(conn, n):
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        except (socket.error, ConnectionResetError, TimeoutError, OSError):
            return None
    return bytes(buf)


def recv_frame(conn):
    len_bytes = recv_exact(conn, 4)
    if len_bytes is None:
        return None
    header_len = struct.unpack("!I", len_bytes)[0]
    if header_len == 0 or header_len > MAX_HEADER_SIZE:
        return None
    raw = recv_exact(conn, header_len)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


# ─── File transfer ────────────────────────────────────────────────────────────
def send_file(conn, filepath, progress_cb=None):
    try:
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)
        file_id = f"{filename}_{uuid.uuid4().hex[:8]}"
        header = {
            "type": "file",
            "filename": filename,
            "file_id": file_id,
            "filesize": filesize,
            "sender": nickname,
        }
        if not send_frame(conn, header):
            return False

        sent = 0
        with open(filepath, "rb") as f:
            while sent < filesize:
                chunk = f.read(FILE_CHUNK_SIZE)
                if not chunk:
                    break
                if not sendall_with_retry(conn, chunk):
                    return False
                sent += len(chunk)
                if progress_cb:
                    progress_cb(sent, filesize)
        return sent == filesize
    except OSError:
        return False


def receive_file(conn, file_info):
    try:
        filename = file_info["filename"]
        file_id = file_info.get("file_id", f"{filename}_{uuid.uuid4().hex[:8]}")
        filesize = int(file_info["filesize"])
        sender = file_info.get("sender", "unknown")

        if filesize < 0 or filesize > 2 * 1024 * 1024 * 1024:
            return False

        received_dir = get_received_dir()
        safe_name = os.path.basename(file_id)
        filepath = os.path.join(received_dir, safe_name)

        with all_files_lock:
            all_files[file_id] = {
                "path": filepath,
                "sender": sender,
                "size": filesize,
                "filename": filename,
            }

        received = 0
        with open(filepath, "wb") as f:
            while received < filesize:
                remaining = filesize - received
                chunk = conn.recv(min(FILE_CHUNK_SIZE, remaining))
                if not chunk:
                    break
                f.write(chunk)
                received += len(chunk)
                # progress to UI
                message_queue.put(
                    {
                        "kind": "file_progress",
                        "file_id": file_id,
                        "received": received,
                        "total": filesize,
                        "direction": "recv",
                    }
                )

        if received >= filesize:
            message_queue.put(
                f"FILE_RECEIVED|{file_id}|{filename}|{sender}|{filesize}"
            )
            return True

        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except OSError:
            pass
        return False
    except (OSError, KeyError, ValueError, TypeError):
        return False


# ─── Client handler ───────────────────────────────────────────────────────────
def handle_client(conn, addr):
    ip = addr[0]

    if not send_frame(
        conn, {"type": "nickname", "nickname": nickname}
    ):
        try:
            conn.close()
        except OSError:
            pass
        return

    try:
        while not stop_event.is_set():
            header = recv_frame(conn)
            if header is None:
                break

            htype = header.get("type")

            if htype == "message":
                body = header.get("body") or header.get("text", "")
                body = decrypt_text(body)
                is_private = bool(header.get("private"))
                target = header.get("to")
                # Only show private msg if it's for us or from room
                if is_private and target and target != nickname:
                    continue
                if body:
                    message_queue.put(
                        {
                            "kind": "message",
                            "text": body,
                            "raw": header.get("text", body),
                            "sender": header.get("sender"),
                            "timestamp": header.get("timestamp"),
                            "style": header.get("style") or {},
                            "private": is_private,
                            "from_ip": ip,
                        }
                    )

            elif htype == "file":
                receive_file(conn, header)

            elif htype == "nickname":
                peer_nick = header.get("nickname", "unknown")
                with peers_lock:
                    connected_peers[ip] = peer_nick
                message_queue.put("PEER_UPDATE")

            elif htype == "ping":
                send_frame(conn, {"type": "pong", "ts": header.get("ts")})

            elif htype == "pong":
                ts = header.get("ts")
                if ts is not None:
                    try:
                        rtt = (time.time() - float(ts)) * 1000
                        with peer_rtt_lock:
                            peer_rtt[ip] = rtt
                        message_queue.put("PEER_UPDATE")
                    except (TypeError, ValueError):
                        pass

            elif htype == "typing":
                message_queue.put(
                    {
                        "kind": "typing",
                        "ip": ip,
                        "nickname": header.get("nickname", "someone"),
                        "private": bool(header.get("private")),
                    }
                )

            elif htype == "system":
                text = header.get("text", "")
                if text:
                    message_queue.put({"kind": "system", "text": text})

    except Exception:
        logging.exception("handle_client %s", ip)
    finally:
        with connection_lock:
            if connections.get(ip) is conn:
                del connections[ip]
        with peers_lock:
            connected_peers.pop(ip, None)
        with peer_rtt_lock:
            peer_rtt.pop(ip, None)
        message_queue.put("PEER_UPDATE")
        try:
            conn.close()
        except OSError:
            pass


# ─── Server ───────────────────────────────────────────────────────────────────
def start_server():
    server_socket = None
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass
        server_socket.bind(("0.0.0.0", PORT))
        server_socket.listen(16)
        server_socket.settimeout(0.5)

        while not stop_event.is_set():
            try:
                conn, addr = server_socket.accept()
                conn.setblocking(True)
                try:
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass
                conn.settimeout(SOCKET_TIMEOUT)
                ip = addr[0]
                with connection_lock:
                    old = connections.get(ip)
                    if old is not None and old is not conn:
                        try:
                            old.close()
                        except OSError:
                            pass
                    connections[ip] = conn
                thread_pool.submit(handle_client, conn, addr)
            except socket.timeout:
                continue
            except OSError:
                if stop_event.is_set():
                    break
                time.sleep(0.05)
    except Exception:
        logging.exception("start_server")
    finally:
        if server_socket:
            try:
                server_socket.close()
            except OSError:
                pass


def connect_to_peer(ip, retry=True):
    local = get_local_ip()
    if ip == local or ip in ("127.0.0.1", "0.0.0.0"):
        return False

    with connection_lock:
        existing = connections.get(ip)
        if existing is not None and is_socket_alive(existing):
            return True
        if existing is not None:
            try:
                existing.close()
            except OSError:
                pass
            del connections[ip]

    attempts = 0
    max_att = MAX_RECONNECT_ATTEMPTS if retry else 1
    while attempts < max_att and not stop_event.is_set():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            sock.connect((ip, PORT))
            sock.setblocking(True)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            sock.settimeout(SOCKET_TIMEOUT)

            with connection_lock:
                if ip in connections and is_socket_alive(connections[ip]):
                    try:
                        sock.close()
                    except OSError:
                        pass
                    return True
                connections[ip] = sock

            thread_pool.submit(handle_client, sock, (ip, PORT))
            return True
        except OSError:
            attempts += 1
            if retry and attempts < max_att:
                time.sleep(0.7 * attempts)
            else:
                return False
    return False


def disconnect_peer(ip):
    with connection_lock:
        sock = connections.pop(ip, None)
        if sock:
            try:
                sock.close()
            except OSError:
                pass
    with peers_lock:
        connected_peers.pop(ip, None)
    with known_peers_lock:
        known_peers.discard(ip)
    with peer_rtt_lock:
        peer_rtt.pop(ip, None)
    message_queue.put("PEER_UPDATE")


def start_broadcast_listener():
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", BROADCAST_PORT))
        sock.settimeout(0.4)
        while not stop_event.is_set():
            try:
                data, addr = sock.recvfrom(BUFFER_SIZE)
                ip = addr[0]
                if ip == get_local_ip():
                    continue
                if data == b"CFE_CHAT_DISCOVERY":
                    with known_peers_lock:
                        known_peers.add(ip)
                    with connection_lock:
                        need = ip not in connections
                    if need:
                        thread_pool.submit(connect_to_peer, ip)
                elif data == b"CFE_CHAT_LEAVING":
                    if ip in connections:
                        disconnect_peer(ip)
            except socket.timeout:
                continue
            except OSError:
                if stop_event.is_set():
                    break
                time.sleep(0.1)
    except Exception:
        logging.exception("broadcast listener")
    finally:
        if sock:
            try:
                sock.close()
            except OSError:
                pass


def broadcast_discovery():
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while not stop_event.is_set():
            try:
                sock.sendto(b"CFE_CHAT_DISCOVERY", ("255.255.255.255", BROADCAST_PORT))
            except OSError:
                pass
            stop_event.wait(DISCOVERY_INTERVAL)
    except Exception:
        logging.exception("broadcast discovery")
    finally:
        if sock:
            try:
                sock.close()
            except OSError:
                pass


def send_leave_notification():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(b"CFE_CHAT_LEAVING", ("255.255.255.255", BROADCAST_PORT))
    except OSError:
        pass


def keepalive_check():
    while not stop_event.is_set():
        try:
            with known_peers_lock:
                peers = list(known_peers)
            for ip in peers:
                if ip == get_local_ip():
                    continue
                with connection_lock:
                    sock = connections.get(ip)
                    alive = sock is not None and is_socket_alive(sock)
                if not alive:
                    thread_pool.submit(connect_to_peer, ip, False)
                else:
                    try:
                        send_frame(sock, {"type": "ping", "ts": time.time()})
                    except Exception:
                        pass
        except Exception:
            logging.exception("keepalive")
        stop_event.wait(PING_INTERVAL)


def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.3)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ":" not in ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return "127.0.0.1"


# ─── Sound / notify ───────────────────────────────────────────────────────────
def play_notify_sound():
    try:
        if platform.system() == "Windows":
            import winsound
            winsound.MessageBeep(winsound.MB_OK)
        else:
            # terminal bell fallback
            sys.stdout.write("\a")
            sys.stdout.flush()
    except Exception:
        pass


# ─── GUI ──────────────────────────────────────────────────────────────────────
class CFEChatGUI:
    def __init__(self, root):
        self.root = root
        self.nickname = nickname
        self.current_chat = "room"  # "room" or peer IP
        self.message_widgets = []
        self._last_date_label = None
        self._peers_update_pending = False
        self._typing_after_id = None
        self._last_typing_sent = 0
        self.sound_enabled = True
        self.history = load_all_history()  # conv_id -> list of msg dicts
        self.file_progress_labels = {}  # file_id -> label widget
        self.tray_icon = None
        self._title_flash_job = None

        # Palette
        self.bg = "#0A0A0F"
        self.panel = "#111118"
        self.panel2 = "#15151F"
        self.panel3 = "#1A1A27"
        self.border = "#252535"
        self.text = "#E8E8F0"
        self.muted = "#8888A0"
        self.accent = "#4FC3F7"
        self.green = "#00E889"
        self.red = "#FF5252"
        self.outgoing = "#17344A"
        self.incoming = "#183B2B"
        self.file_bubble = "#302A16"
        self.hover = "#242438"
        self.selected = "#1E3041"

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root.title(f"CFE Chat {VERSION}")
        self.root.geometry("1180x740")
        self.root.minsize(940, 620)
        self.root.configure(bg=self.bg)

        self.main_container = ctk.CTkFrame(root, fg_color=self.bg, corner_radius=14)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(1, weight=0, minsize=300)
        self.main_container.grid_rowconfigure(0, weight=1)

        self.create_main_area()
        self.create_sidebar()

        self.bold_active = False
        self.italic_active = False
        self.text_color = self.text

        self._load_conversation_into_ui("room")
        self.process_messages()
        self.start_network()

        local_ip = get_local_ip()
        enc = "  •  encrypted" if fernet else ""
        self.add_system_message(f"CFE Chat {VERSION} started  •  LAN: {local_ip}{enc}")
        join_msg = f"{self.nickname} joined [{datetime.now().strftime('%d.%m.%Y %H:%M')}]"
        write_to_log(join_msg)
        self.broadcast_system(join_msg)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close_request)
        self.root.bind("<Control-Return>", lambda e: self.send_message())
        self.root.bind("<Control-v>", self.on_paste)
        self.root.bind("<Control-V>", self.on_paste)

        if HAS_TRAY:
            self._setup_tray()

    # ── Layout ────────────────────────────────────────────────────────────────
    def create_sidebar(self):
        self.sidebar = ctk.CTkFrame(
            self.main_container,
            fg_color=self.panel,
            corner_radius=12,
            border_width=1,
            border_color=self.border,
            width=290,
        )
        self.sidebar.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(3, weight=1)

        top = ctk.CTkFrame(self.sidebar, fg_color="transparent", height=56)
        top.pack(fill=tk.X, padx=14, pady=(14, 2))
        top.pack_propagate(False)
        ctk.CTkLabel(
            top, text="CFE", font=ctk.CTkFont(size=26, weight="bold"),
            text_color=self.accent, anchor="w",
        ).pack(side=tk.LEFT, pady=(2, 0))
        ctk.CTkLabel(
            top, text=f"Chat {VERSION}", font=ctk.CTkFont(size=12),
            text_color=self.muted,
        ).pack(side=tk.LEFT, padx=(8, 0), pady=(12, 0))

        # Me card
        self.me_card = ctk.CTkFrame(
            self.sidebar, fg_color=self.panel3, corner_radius=12,
            border_width=1, border_color=self.border,
        )
        self.me_card.pack(fill=tk.X, padx=10, pady=(6, 10))

        ctk.CTkLabel(
            self.me_card, text="●", text_color=self.green,
            font=ctk.CTkFont(size=16, weight="bold"), width=26,
        ).pack(side=tk.LEFT, padx=(10, 0), pady=12)

        me_text = ctk.CTkFrame(self.me_card, fg_color="transparent")
        me_text.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=10)
        ctk.CTkLabel(
            me_text, text=f"{self.nickname}  (you)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=self.text, anchor="w",
        ).pack(fill=tk.X)
        ctk.CTkLabel(
            me_text, text="Online  •  LAN",
            font=ctk.CTkFont(size=11), text_color=self.green, anchor="w",
        ).pack(fill=tk.X)

        # Contacts header
        hdr = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        hdr.pack(fill=tk.X, padx=12, pady=(2, 4))
        ctk.CTkLabel(
            hdr, text="CONTACTS", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=self.muted, anchor="w",
        ).pack(side=tk.LEFT)
        ctk.CTkButton(
            hdr, text="Room", width=58, height=24, corner_radius=6,
            fg_color=self.panel2, hover_color=self.hover, text_color=self.text,
            font=ctk.CTkFont(size=11), command=self.show_room,
        ).pack(side=tk.RIGHT)

        self.peers_frame = ctk.CTkScrollableFrame(
            self.sidebar, fg_color="transparent", corner_radius=0,
            scrollbar_fg_color=self.panel, scrollbar_button_color="#303044",
            scrollbar_button_hover_color="#41415A",
        )
        self.peers_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))
        self.update_peers_list()

        footer = ctk.CTkFrame(self.sidebar, fg_color="transparent", height=42)
        footer.pack(fill=tk.X, padx=12, pady=(0, 10))
        footer.pack_propagate(False)
        self.users_label = ctk.CTkLabel(
            footer, text="Online: 1", font=ctk.CTkFont(size=12), text_color=self.muted,
        )
        self.users_label.pack(side=tk.LEFT, pady=6)
        ctk.CTkButton(
            footer, text="📁", width=34, height=30, corner_radius=6,
            fg_color=self.panel2, hover_color=self.hover, text_color=self.text,
            font=ctk.CTkFont(size=15), command=self.open_received_folder,
        ).pack(side=tk.RIGHT, padx=(4, 0))
        self.sound_btn = ctk.CTkButton(
            footer, text="🔔", width=34, height=30, corner_radius=6,
            fg_color=self.panel2, hover_color=self.hover, text_color=self.text,
            font=ctk.CTkFont(size=15), command=self.toggle_sound,
        )
        self.sound_btn.pack(side=tk.RIGHT)

    def create_main_area(self):
        self.main_area = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.main_area.grid(row=0, column=0, sticky="nsew")
        self.main_area.grid_columnconfigure(0, weight=1)
        self.main_area.grid_rowconfigure(1, weight=1)

        self.create_header()
        self.create_chat_area()
        self.create_input_area()
        self.create_bottom_bar()

    def create_header(self):
        self.header_frame = ctk.CTkFrame(
            self.main_area, fg_color=self.panel, corner_radius=10,
            border_width=1, border_color=self.border, height=68,
        )
        self.header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.header_frame.grid_propagate(False)
        self.header_frame.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            self.header_frame, text="CFE Chat — Local Room",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=self.text, anchor="w",
        )
        self.title_label.grid(row=0, column=0, sticky="w", padx=16, pady=(10, 0))

        self.subtitle_label = ctk.CTkLabel(
            self.header_frame,
            text="Everyone on this LAN sees messages",
            font=ctk.CTkFont(size=11), text_color=self.muted, anchor="w",
        )
        self.subtitle_label.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 10))

        self.typing_label = ctk.CTkLabel(
            self.header_frame, text="", font=ctk.CTkFont(size=11),
            text_color=self.accent, anchor="e",
        )
        self.typing_label.grid(row=0, column=1, rowspan=2, sticky="e", padx=16)

    def create_chat_area(self):
        self.chat_frame = ctk.CTkScrollableFrame(
            self.main_area, fg_color=self.panel, corner_radius=10,
            border_width=1, border_color=self.border,
            scrollbar_fg_color=self.panel, scrollbar_button_color="#303044",
            scrollbar_button_hover_color="#41415A",
        )
        self.chat_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 8))

    def create_input_area(self):
        input_frame = ctk.CTkFrame(
            self.main_area, fg_color=self.panel, corner_radius=10,
            border_width=1, border_color=self.border, height=120,
        )
        input_frame.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        input_frame.grid_propagate(False)

        toolbar = ctk.CTkFrame(input_frame, fg_color="transparent", height=34)
        toolbar.pack(fill=tk.X, padx=8, pady=(6, 0))
        toolbar.pack_propagate(False)

        self.bold_btn = ctk.CTkButton(
            toolbar, text="B", width=36, height=30, corner_radius=7,
            fg_color=self.panel2, hover_color=self.hover, text_color=self.text,
            border_width=1, border_color=self.border,
            font=ctk.CTkFont(size=14, weight="bold"), command=self.toggle_bold,
        )
        self.bold_btn.pack(side=tk.LEFT, padx=(0, 4))

        self.italic_btn = ctk.CTkButton(
            toolbar, text="I", width=36, height=30, corner_radius=7,
            fg_color=self.panel2, hover_color=self.hover, text_color=self.text,
            border_width=1, border_color=self.border,
            font=ctk.CTkFont(size=14, slant="italic"), command=self.toggle_italic,
        )
        self.italic_btn.pack(side=tk.LEFT, padx=4)

        self.color_btn = ctk.CTkButton(
            toolbar, text="A  Color", width=88, height=30, corner_radius=7,
            fg_color=self.panel2, hover_color=self.hover, text_color=self.text,
            border_width=1, border_color=self.border,
            font=ctk.CTkFont(size=12), command=self.choose_text_color,
        )
        self.color_btn.pack(side=tk.LEFT, padx=4)

        self.format_label = ctk.CTkLabel(
            toolbar, text="Normal", font=ctk.CTkFont(size=11), text_color=self.muted,
        )
        self.format_label.pack(side=tk.LEFT, padx=10)

        self.input_entry = ctk.CTkEntry(
            input_frame, font=ctk.CTkFont(size=15),
            fg_color=self.panel2, text_color=self.text,
            placeholder_text="Message…  Enter to send  •  Ctrl+V paste image",
            placeholder_text_color=self.muted,
            height=50, corner_radius=9, border_width=1, border_color=self.border,
        )
        self.input_entry.pack(fill=tk.X, expand=True, padx=8, pady=(4, 10))
        self.input_entry.bind("<Return>", self.send_message)
        self.input_entry.bind("<KeyPress>", self.on_key_typing)
        self.input_entry.focus_set()

    def create_bottom_bar(self):
        bottom = ctk.CTkFrame(self.main_area, fg_color="transparent", height=40)
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.grid_propagate(False)

        common = dict(
            font=ctk.CTkFont(size=12), fg_color=self.panel, hover_color=self.hover,
            text_color=self.text, corner_radius=7, height=34,
            border_width=1, border_color=self.border,
        )
        ctk.CTkButton(
            bottom, text="Attach File", width=115, command=self.send_file_dialog, **common
        ).pack(side=tk.LEFT, padx=(0, 6))
        ctk.CTkButton(
            bottom, text="Telegram", width=100, command=self.open_telegram_channel, **common
        ).pack(side=tk.LEFT, padx=4)
        ctk.CTkButton(
            bottom, text="Clear Chat", width=105, command=self.clear_chat,
            fg_color=self.panel, hover_color="#4A242A", text_color=self.text,
            border_width=1, border_color=self.border, corner_radius=7, height=34,
            font=ctk.CTkFont(size=12),
        ).pack(side=tk.LEFT, padx=4)

        ctk.CTkButton(
            bottom, text="Send", width=100, command=self.send_message,
            fg_color="#245E78", hover_color="#2D7898", text_color="#FFFFFF",
            corner_radius=7, height=34, border_width=1, border_color="#367E9B",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side=tk.RIGHT)

    # ── Peers / contacts ──────────────────────────────────────────────────────
    def schedule_peers_update(self):
        if self._peers_update_pending:
            return
        self._peers_update_pending = True
        self.root.after(80, self._do_peers_update)

    def _do_peers_update(self):
        self._peers_update_pending = False
        self.update_peers_list()

    def update_peers_list(self):
        try:
            for w in self.peers_frame.winfo_children():
                w.destroy()

            with peers_lock:
                online = dict(connected_peers)
            with saved_contacts_lock:
                saved = dict(saved_contacts)

            # Merge: all saved + currently online
            all_ips = set(online.keys()) | set(saved.keys())

            if not all_ips:
                ctk.CTkLabel(
                    self.peers_frame,
                    text="No contacts yet.\nChat with someone —\nthey will appear here.",
                    font=ctk.CTkFont(size=12), text_color=self.muted,
                    justify="left", anchor="w",
                ).pack(fill=tk.X, padx=8, pady=16)
            else:
                # Online first, then offline saved
                def sort_key(ip):
                    nick = online.get(ip) or saved.get(ip, {}).get("nickname", ip)
                    is_on = 0 if ip in online else 1
                    return (is_on, nick.lower())

                for ip in sorted(all_ips, key=sort_key):
                    nick = online.get(ip) or saved.get(ip, {}).get("nickname", ip)
                    is_online = ip in online
                    self._add_peer_row(ip, nick, is_online)

            with connection_lock:
                n_online = len(connections) + 1
            self.users_label.configure(text=f"Online: {n_online}")
        except Exception:
            logging.exception("update_peers_list")

    def _add_peer_row(self, ip, peer_nickname, is_online):
        selected = self.current_chat == ip
        status_color = self.green if is_online else self.red
        status_text = "Online" if is_online else "Offline"

        with peer_rtt_lock:
            rtt = peer_rtt.get(ip)
        quality = ""
        if is_online and rtt is not None:
            if rtt < 30:
                quality = f"  •  {rtt:.0f} ms ●"
            elif rtt < 80:
                quality = f"  •  {rtt:.0f} ms ●"
            else:
                quality = f"  •  {rtt:.0f} ms ●"

        row = ctk.CTkFrame(
            self.peers_frame,
            fg_color=self.selected if selected else self.panel2,
            corner_radius=9,
            border_width=1 if selected else 0,
            border_color="#315B75",
            height=56,
        )
        row.pack(fill=tk.X, pady=3, padx=2)
        row.pack_propagate(False)

        ctk.CTkLabel(
            row, text="●", text_color=status_color,
            font=ctk.CTkFont(size=15, weight="bold"), width=24,
        ).pack(side=tk.LEFT, padx=(8, 0))

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(2, 6), pady=7)
        name = ctk.CTkLabel(
            info, text=peer_nickname, text_color=self.text,
            font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        )
        name.pack(fill=tk.X)
        sub = ctk.CTkLabel(
            info, text=f"{status_text}{quality}",
            text_color=status_color if not is_online else self.muted,
            font=ctk.CTkFont(size=10), anchor="w",
        )
        sub.pack(fill=tk.X)

        def on_click(_e, p=ip, n=peer_nickname):
            self.select_peer(p, n)

        def on_right(_e, p=ip, n=peer_nickname):
            self._peer_context_menu(p, n)

        for w in (row, info, name, sub):
            w.bind("<Button-1>", on_click)
            w.bind("<Button-3>", on_right)

    def _peer_context_menu(self, ip, nick):
        menu = tk.Menu(self.root, tearoff=0, bg=self.panel2, fg=self.text,
                       activebackground=self.hover, activeforeground=self.text)
        menu.add_command(label=f"Copy IP: {ip}", command=lambda: self._copy_text(ip))
        menu.add_command(label=f"Open chat with {nick}", command=lambda: self.select_peer(ip, nick))
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def select_peer(self, ip, peer_nickname):
        self.current_chat = ip
        self.title_label.configure(text=peer_nickname)
        online = ip in connected_peers
        status = "Online" if online else "Offline"
        self.subtitle_label.configure(text=f"Private chat  •  {ip}  •  {status}")
        self._clear_chat_widgets()
        self._load_conversation_into_ui(f"dm:{ip}")
        self.schedule_peers_update()

    def show_room(self):
        self.current_chat = "room"
        self.title_label.configure(text="CFE Chat — Local Room")
        self.subtitle_label.configure(text="Everyone on this LAN sees messages")
        self._clear_chat_widgets()
        self._load_conversation_into_ui("room")
        self.schedule_peers_update()

    # ── History UI ────────────────────────────────────────────────────────────
    def _conv_key(self):
        if self.current_chat == "room":
            return "room"
        return f"dm:{self.current_chat}"

    def _append_history(self, conv_key, entry):
        if conv_key not in self.history:
            self.history[conv_key] = []
        self.history[conv_key].append(entry)
        if len(self.history[conv_key]) > HISTORY_LIMIT:
            self.history[conv_key] = self.history[conv_key][-HISTORY_LIMIT:]
        save_all_history(self.history)

    def _load_conversation_into_ui(self, conv_key):
        self._last_date_label = None
        msgs = self.history.get(conv_key, [])
        for m in msgs:
            kind = m.get("kind", "message")
            if kind == "system":
                self.add_system_message(m.get("text", ""), save=False)
            elif kind == "file":
                self.add_file_bubble(
                    m.get("file_id", ""), m.get("filename", "?"),
                    m.get("sender", "?"), m.get("size", 0),
                    m.get("status", "received"), save=False,
                )
            else:
                self.add_message_bubble(
                    m.get("text", ""), m.get("sender", "?"),
                    m.get("timestamp", ""), is_self=m.get("is_self", False),
                    style=m.get("style"), save=False,
                )

    def _clear_chat_widgets(self):
        for w in self.chat_frame.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self.message_widgets.clear()
        self.file_progress_labels.clear()
        self._last_date_label = None

    # ── Messages UI ───────────────────────────────────────────────────────────
    def _cleanup_old_messages(self):
        if len(self.message_widgets) > MAX_MESSAGES_UI:
            for w in self.message_widgets[:-MAX_MESSAGES_UI]:
                try:
                    w.destroy()
                except Exception:
                    pass
            self.message_widgets = self.message_widgets[-MAX_MESSAGES_UI:]

    def _scroll_bottom(self):
        try:
            self.chat_frame._parent_canvas.update_idletasks()
            self.chat_frame._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _maybe_date_separator(self, timestamp_str):
        try:
            day = timestamp_str.split(" ")[0]
            if day != self._last_date_label:
                self._last_date_label = day
                frame = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
                frame.pack(fill=tk.X, pady=(14, 4), padx=10)
                ctk.CTkLabel(
                    frame, text=f"—  {day}  —",
                    font=ctk.CTkFont(size=11), text_color=self.muted,
                ).pack()
                self.message_widgets.append(frame)
        except Exception:
            pass

    def add_system_message(self, text, save=True):
        try:
            frame = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
            frame.pack(fill=tk.X, pady=6, padx=12)
            ctk.CTkLabel(
                frame, text=text, font=ctk.CTkFont(size=12),
                text_color=self.muted, wraplength=700,
            ).pack()
            self.message_widgets.append(frame)
            self._cleanup_old_messages()
            self._scroll_bottom()
            if save:
                self._append_history(self._conv_key(), {"kind": "system", "text": text})
        except Exception:
            pass

    def add_message_bubble(self, text, sender, timestamp, is_self=False, style=None, save=True):
        try:
            self._maybe_date_separator(timestamp)
            outer = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
            outer.pack(fill=tk.X, pady=4, padx=10)

            bubble = ctk.CTkFrame(
                outer,
                fg_color=self.outgoing if is_self else self.incoming,
                corner_radius=12,
                border_width=1,
                border_color="#24506A" if is_self else "#24583D",
            )
            bubble.pack(
                side=tk.RIGHT if is_self else tk.LEFT,
                padx=(70, 4) if is_self else (4, 70),
            )

            meta = ctk.CTkLabel(
                bubble, text=f"{sender}  •  {timestamp}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#8EB6C9" if is_self else "#8FC8A7",
                anchor="w",
            )
            meta.pack(anchor="w", padx=13, pady=(8, 0))

            style = style or {}
            font_kwargs = {"size": 15}
            if style.get("bold"):
                font_kwargs["weight"] = "bold"
            if style.get("italic"):
                font_kwargs["slant"] = "italic"
            msg_color = style.get("color") or self.text

            msg_label = ctk.CTkLabel(
                bubble, text=text, font=ctk.CTkFont(**font_kwargs),
                text_color=msg_color, wraplength=660, justify="left", anchor="w",
            )
            msg_label.pack(anchor="w", padx=13, pady=(3, 11))

            def copy_msg(_e=None, t=text):
                self._copy_text(t)

            for w in (bubble, meta, msg_label):
                w.bind("<Button-3>", copy_msg)

            self.message_widgets.append(outer)
            self._cleanup_old_messages()
            self._scroll_bottom()

            if save:
                self._append_history(
                    self._conv_key(),
                    {
                        "kind": "message",
                        "text": text,
                        "sender": sender,
                        "timestamp": timestamp,
                        "is_self": is_self,
                        "style": style,
                    },
                )
        except Exception:
            logging.exception("add_message_bubble")

    def add_file_bubble(self, file_id, filename, sender, size, status="received", save=True, progress=None):
        try:
            if size < 1024 * 1024:
                size_text = f"{size / 1024:.1f} KB"
            else:
                size_text = f"{size / (1024 * 1024):.1f} MB"
            outgoing = status == "sent"

            outer = ctk.CTkFrame(self.chat_frame, fg_color="transparent")
            outer.pack(fill=tk.X, pady=4, padx=10)

            bubble = ctk.CTkFrame(
                outer, fg_color=self.file_bubble, corner_radius=12,
                border_width=1, border_color="#655528",
            )
            bubble.pack(
                side=tk.RIGHT if outgoing else tk.LEFT,
                padx=(70, 4) if outgoing else (4, 70),
            )

            ctk.CTkLabel(
                bubble, text=f"{sender}  •  File",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#D8BE6A", anchor="w",
            ).pack(anchor="w", padx=13, pady=(8, 0))

            icon = "✓" if outgoing and progress is None else ("📤" if outgoing else "📥")
            btn = ctk.CTkButton(
                bubble,
                text=f"{icon}  {filename}  ({size_text})",
                font=ctk.CTkFont(size=13), fg_color="transparent",
                hover_color="#403719", text_color="#D8BE6A", anchor="w",
                command=lambda fid=file_id: self.download_file(fid),
            )
            btn.pack(fill=tk.X, padx=6, pady=(2, 4))

            prog_label = ctk.CTkLabel(
                bubble, text="", font=ctk.CTkFont(size=11),
                text_color="#A09050", anchor="w",
            )
            prog_label.pack(anchor="w", padx=13, pady=(0, 8))
            if progress is not None:
                pct = int(100 * progress[0] / max(progress[1], 1))
                prog_label.configure(text=f"{pct}%")
            self.file_progress_labels[file_id] = prog_label

            self.message_widgets.append(outer)
            self._cleanup_old_messages()
            self._scroll_bottom()

            if save:
                self._append_history(
                    self._conv_key(),
                    {
                        "kind": "file",
                        "file_id": file_id,
                        "filename": filename,
                        "sender": sender,
                        "size": size,
                        "status": status,
                    },
                )
        except Exception:
            logging.exception("add_file_bubble")

    def _copy_text(self, text):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.add_system_message("Copied to clipboard")
        except Exception:
            pass

    # ── Formatting ────────────────────────────────────────────────────────────
    def _refresh_format_ui(self):
        self.bold_btn.configure(
            fg_color=self.accent if self.bold_active else self.panel2,
            text_color="#FFFFFF" if self.bold_active else self.text,
        )
        self.italic_btn.configure(
            fg_color=self.accent if self.italic_active else self.panel2,
            text_color="#FFFFFF" if self.italic_active else self.text,
        )
        parts = []
        if self.bold_active:
            parts.append("Bold")
        if self.italic_active:
            parts.append("Italic")
        parts.append("Default" if self.text_color == self.text else self.text_color.upper())
        self.format_label.configure(text=" • ".join(parts))

    def toggle_bold(self):
        self.bold_active = not self.bold_active
        self._refresh_format_ui()

    def toggle_italic(self):
        self.italic_active = not self.italic_active
        self._refresh_format_ui()

    def choose_text_color(self):
        color = colorchooser.askcolor(
            color=self.text_color, parent=self.root, title="Message color"
        )[1]
        if color:
            self.text_color = color
            self._refresh_format_ui()

    def toggle_sound(self):
        self.sound_enabled = not self.sound_enabled
        self.sound_btn.configure(text="🔔" if self.sound_enabled else "🔕")

    # ── Typing ────────────────────────────────────────────────────────────────
    def on_key_typing(self, event):
        now = time.time()
        if now - self._last_typing_sent < 1.5:
            return
        self._last_typing_sent = now
        payload = {
            "type": "typing",
            "nickname": self.nickname,
            "private": self.current_chat != "room",
        }
        if self.current_chat == "room":
            self.broadcast_message(payload)
        else:
            self._send_to_ip(self.current_chat, payload)

    def _show_typing(self, nick):
        self.typing_label.configure(text=f"{nick} is typing…")
        if self._typing_after_id:
            self.root.after_cancel(self._typing_after_id)
        self._typing_after_id = self.root.after(
            2500, lambda: self.typing_label.configure(text="")
        )

    # ── Send / receive ────────────────────────────────────────────────────────
    def send_message(self, event=None):
        try:
            message = self.input_entry.get().strip()
            if not message:
                return "break" if event else None

            timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
            style = {
                "bold": self.bold_active,
                "italic": self.italic_active,
                "color": self.text_color,
            }
            enc_body = encrypt_text(message)
            is_private = self.current_chat != "room"

            payload = {
                "type": "message",
                "body": enc_body,
                "text": f"{self.nickname} [{timestamp}]>>> {message}",
                "sender": self.nickname,
                "timestamp": timestamp,
                "style": style,
                "private": is_private,
            }
            if is_private:
                # target nickname for filtering on other side
                with peers_lock:
                    target_nick = connected_peers.get(self.current_chat, "")
                payload["to"] = target_nick

            write_to_log(payload["text"])
            self.add_message_bubble(
                message, self.nickname, timestamp, is_self=True, style=style
            )

            if is_private:
                self._send_to_ip(self.current_chat, payload)
                # remember contact
                with peers_lock:
                    nick = connected_peers.get(self.current_chat, self.current_chat)
                remember_contact(self.current_chat, nick)
            else:
                self.broadcast_message(payload)

            self.input_entry.delete(0, tk.END)
        except Exception as exc:
            self.add_system_message(f"Send error: {exc}")
        return "break" if event else None

    def _send_to_ip(self, ip, data):
        with connection_lock:
            conn = connections.get(ip)
        if conn:
            send_frame(conn, data)
        else:
            self.add_system_message("Peer is offline — message not delivered.")

    def broadcast_message(self, data):
        with connection_lock:
            conns = list(connections.items())
        for ip, conn in conns:
            if isinstance(data, dict):
                send_frame(conn, data)
            else:
                send_frame(conn, {"type": "message", "text": str(data), "body": str(data)})

    def broadcast_system(self, text):
        self.broadcast_message({"type": "system", "text": text})

    def send_file_dialog(self):
        try:
            filepath = filedialog.askopenfilename(
                parent=self.root, title="Select file to send"
            )
            if not filepath:
                return
            self._start_file_send(filepath)
        except Exception as exc:
            messagebox.showerror("Send File", str(exc), parent=self.root)

    def _start_file_send(self, filepath):
        filesize = os.path.getsize(filepath)
        filename = os.path.basename(filepath)
        is_private = self.current_chat != "room"
        target = "this contact" if is_private else "everyone online"
        if not messagebox.askyesno(
            "Send File",
            f"Send «{filename}» ({filesize // 1024} KB) to {target}?",
            parent=self.root,
        ):
            return
        file_id = f"{filename}_{uuid.uuid4().hex[:8]}"
        self.add_file_bubble(
            file_id, filename, self.nickname, filesize, status="sent",
            progress=(0, filesize),
        )
        thread_pool.submit(self.send_file_thread, filepath, file_id, is_private)

    def send_file_thread(self, filepath, file_id, is_private):
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)
        with all_files_lock:
            all_files[file_id] = {
                "path": filepath,
                "sender": self.nickname,
                "size": filesize,
                "filename": filename,
            }

        def progress_cb(sent, total):
            message_queue.put(
                {
                    "kind": "file_progress",
                    "file_id": file_id,
                    "received": sent,
                    "total": total,
                    "direction": "send",
                }
            )

        if is_private:
            with connection_lock:
                conn = connections.get(self.current_chat)
            if not conn:
                self.root.after(0, lambda: self.add_system_message("Peer offline."))
                return
            ok = send_file(conn, filepath, progress_cb)
            if ok:
                write_to_log(f"{self.nickname} sent file (DM): {filename}")
                with peers_lock:
                    nick = connected_peers.get(self.current_chat, self.current_chat)
                remember_contact(self.current_chat, nick)
            else:
                self.root.after(0, lambda: self.add_system_message("File transfer failed."))
        else:
            with connection_lock:
                conns = list(connections.items())
            if not conns:
                self.root.after(0, lambda: self.add_system_message("No one is connected."))
                return
            ok_count = 0
            for ip, conn in conns:
                if send_file(conn, filepath, progress_cb):
                    ok_count += 1
            if ok_count:
                write_to_log(f"{self.nickname} sent file: {filename}")
            self.root.after(
                0,
                lambda: self.add_system_message(
                    f"File: {ok_count}/{len(conns)} peers ok."
                ),
            )

    def download_file(self, file_id):
        source = None
        filename = None
        with all_files_lock:
            info = all_files.get(file_id)
            if info:
                source = info["path"]
                filename = info.get("filename", file_id)

        if not source or not os.path.exists(source):
            messagebox.showerror("File", "File not found.", parent=self.root)
            return
        try:
            os.makedirs(DOWNLOADS_FOLDER, exist_ok=True)
            dest = os.path.join(DOWNLOADS_FOLDER, filename)
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(dest):
                dest = os.path.join(DOWNLOADS_FOLDER, f"{base}_{counter}{ext}")
                counter += 1
            shutil.copy2(source, dest)
            messagebox.showinfo("Download Complete", f"Saved:\n{dest}", parent=self.root)
        except Exception as e:
            messagebox.showerror("Download Error", str(e), parent=self.root)

    def open_received_folder(self):
        path = get_received_dir()
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')
        except Exception:
            messagebox.showinfo("Folder", path, parent=self.root)

    def open_telegram_channel(self):
        webbrowser.open(TG_CHANNEL_URL)

    def clear_chat(self):
        key = self._conv_key()
        self.history[key] = []
        save_all_history(self.history)
        self._clear_chat_widgets()
        self.add_system_message("Chat history cleared for this conversation.")

    # ── Paste image ───────────────────────────────────────────────────────────
    def on_paste(self, event=None):
        if not HAS_PIL:
            return
        try:
            img = ImageGrab.grabclipboard()
            if img is None:
                return  # not an image
            if not isinstance(img, Image.Image):
                return
            tmp_dir = os.path.join(get_data_dir(), "temp")
            os.makedirs(tmp_dir, exist_ok=True)
            path = os.path.join(tmp_dir, f"paste_{uuid.uuid4().hex[:8]}.png")
            img.save(path, "PNG")
            self._start_file_send(path)
            return "break"
        except Exception:
            logging.exception("paste image")

    # ── Notify ────────────────────────────────────────────────────────────────
    def _notify_new_message(self, sender):
        if self.sound_enabled:
            play_notify_sound()
        # Flash title if not focused
        try:
            if self.root.focus_displayof() is None:
                self._flash_title(sender)
        except Exception:
            self._flash_title(sender)

    def _flash_title(self, sender):
        original = self.root.title()
        self.root.title(f"💬 {sender}: new message — CFE Chat")
        if self._title_flash_job:
            self.root.after_cancel(self._title_flash_job)

        def restore():
            self.root.title(original)
            self._title_flash_job = None

        self._title_flash_job = self.root.after(4000, restore)

    # ── Message pump ──────────────────────────────────────────────────────────
    def process_messages(self):
        try:
            while not message_queue.empty():
                msg = message_queue.get_nowait()

                if msg == "PEER_UPDATE":
                    self.schedule_peers_update()

                elif isinstance(msg, dict) and msg.get("kind") == "typing":
                    # show only if relevant to current view
                    if self.current_chat == "room" and not msg.get("private"):
                        self._show_typing(msg.get("nickname", "?"))
                    elif self.current_chat == msg.get("ip"):
                        self._show_typing(msg.get("nickname", "?"))

                elif isinstance(msg, dict) and msg.get("kind") == "file_progress":
                    fid = msg.get("file_id")
                    lbl = self.file_progress_labels.get(fid)
                    if lbl:
                        rec, total = msg["received"], msg["total"]
                        pct = int(100 * rec / max(total, 1))
                        direction = msg.get("direction", "")
                        lbl.configure(text=f"{pct}%  ({direction})")

                elif isinstance(msg, dict) and msg.get("kind") == "message":
                    sender = msg.get("sender")
                    timestamp = msg.get("timestamp")
                    body = msg.get("text") or ""
                    is_private = msg.get("private", False)
                    from_ip = msg.get("from_ip")

                    # Decide which conversation this belongs to
                    if is_private and from_ip:
                        conv = f"dm:{from_ip}"
                        # remember contact
                        remember_contact(from_ip, sender or from_ip)
                    else:
                        conv = "room"

                    # Only display if we are viewing that conversation
                    show = (conv == self._conv_key())

                    if sender and timestamp:
                        if show:
                            self.add_message_bubble(
                                body, sender, timestamp,
                                is_self=(sender == self.nickname),
                                style=msg.get("style") or {},
                            )
                        else:
                            # still save to history
                            self._append_history(
                                conv,
                                {
                                    "kind": "message",
                                    "text": body,
                                    "sender": sender,
                                    "timestamp": timestamp,
                                    "is_self": sender == self.nickname,
                                    "style": msg.get("style") or {},
                                },
                            )
                        write_to_log(msg.get("raw", body))
                        if sender != self.nickname:
                            self._notify_new_message(sender)
                    self.schedule_peers_update()

                elif isinstance(msg, dict) and msg.get("kind") == "system":
                    if self.current_chat == "room":
                        self.add_system_message(msg.get("text", ""))
                    write_to_log(msg.get("text", ""))

                elif isinstance(msg, str) and msg.startswith("FILE_RECEIVED|"):
                    parts = msg.split("|")
                    if len(parts) >= 5:
                        file_id, filename, sender = parts[1], parts[2], parts[3]
                        size = int(parts[4])
                        # files currently always treated as current view
                        self.add_file_bubble(
                            file_id, filename, sender, size, "received"
                        )
                        write_to_log(f"File received: {filename} from {sender}")
                        if sender != self.nickname:
                            self._notify_new_message(sender)

                elif isinstance(msg, str):
                    if "joined" in msg or "left" in msg:
                        if self.current_chat == "room":
                            self.add_system_message(msg)
                        write_to_log(msg)
                    else:
                        self.add_system_message(msg)
        except Exception:
            logging.exception("process_messages")

        if not stop_event.is_set():
            self.root.after(90, self.process_messages)

    def start_network(self):
        thread_pool.submit(start_server)
        thread_pool.submit(start_broadcast_listener)
        thread_pool.submit(broadcast_discovery)
        thread_pool.submit(keepalive_check)

    # ── Tray ──────────────────────────────────────────────────────────────────
    def _setup_tray(self):
        if not HAS_TRAY or not HAS_PIL:
            return
        try:
            # simple icon
            img = Image.new("RGB", (64, 64), color=(79, 195, 247))
            menu = pystray.Menu(
                TrayMenuItem("Show", self._tray_show),
                TrayMenuItem("Quit", self._tray_quit),
            )
            self.tray_icon = pystray.Icon("CFE Chat", img, "CFE Chat", menu)
            thread_pool.submit(self.tray_icon.run)
        except Exception:
            logging.exception("tray setup")
            self.tray_icon = None

    def _tray_show(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)

    def _tray_quit(self, icon=None, item=None):
        self.root.after(0, self.on_close)

    def on_close_request(self):
        if self.tray_icon:
            self.root.withdraw()
        else:
            self.on_close()

    def on_close(self):
        try:
            leave = f"{self.nickname} left [{datetime.now().strftime('%d.%m.%Y %H:%M')}]"
            write_to_log(leave)
            self.broadcast_system(leave)
            send_leave_notification()
        except Exception:
            pass

        stop_event.set()
        save_all_history(self.history)
        save_contacts()

        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass

        try:
            with connection_lock:
                for conn in list(connections.values()):
                    try:
                        conn.close()
                    except OSError:
                        pass
                connections.clear()
        except Exception:
            pass

        try:
            if sys.version_info >= (3, 9):
                thread_pool.shutdown(wait=False, cancel_futures=True)
            else:
                thread_pool.shutdown(wait=False)
        except Exception:
            pass

        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass


# ─── Entry ────────────────────────────────────────────────────────────────────
def main():
    global nickname, fernet

    get_data_dir()
    setup_logging()
    ensure_log_file()
    load_contacts()
    nickname = load_nickname()

    root = ctk.CTk()

    if not nickname:
        dialog = ctk.CTkInputDialog(
            text="Choose your name:", title=f"CFE Chat {VERSION}"
        )
        nickname = dialog.get_input()
        if not nickname or not nickname.strip():
            nickname = "User"
        else:
            nickname = nickname.strip()[:32]
        save_nickname(nickname)

    # Optional shared secret for encryption
    if HAS_CRYPTO:
        secret_dialog = ctk.CTkInputDialog(
            text="Shared secret for encryption (empty = off):",
            title="Encryption (optional)",
        )
        secret = secret_dialog.get_input()
        if secret and secret.strip():
            fernet = derive_fernet(secret.strip())

    CFEChatGUI(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down...")
        stop_event.set()
        sys.exit(0)
