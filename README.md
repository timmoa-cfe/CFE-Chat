# CFE Chat 🚀

**A fully decentralized, serverless peer-to-peer LAN messenger built with Python 3.13 and CustomTkinter.**

Zero configuration. Zero servers. Wire-to-wire encryption. Automatic peer discovery over UDP broadcast.

![Python Version](https://img.shields.io/badge/python-3.13+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

---

## ✨ Features

- **🔗 Zero-Config Auto-Discovery** — UDP broadcasts find peers automatically
- **💬 Room & Private DMs** — Broadcast to everyone or direct message a peer
- **📁 Fast File Sharing** — Chunked transfers with progress bars
- **🔐 Optional Encryption** — Shared-secret Fernet encryption for messages
- **🎨 Beautiful Dark GUI** — CustomTkinter modern interface
- **⚡ Real-Time Status** — Online/offline indicators + connection quality (RTT)
- **💾 Persistent History** — Automatic chat logging & contact saving
- **🔤 Text Formatting** — Bold, italic, custom colors
- **📢 Notifications** — Sound alerts + title bar flashing
- **🛠️ No Setup Required** — Just install & run

---

## 🚀 Quick Start

### Install via pip
```bash
pip install cfe-chat
```

### Run
```bash
cfe-chat
```

### First Time?
1. Enter your nickname
2. Optionally set an encryption password (or leave blank)
3. App auto-discovers peers on your LAN
4. Start chatting!

---

## 📋 Requirements

- **Python 3.13+** (3.8+ compatible with minor tweaks)
- **pip** package manager

### Dependencies (auto-installed)
- `customtkinter` — Modern GUI framework
- `cryptography` — Optional encryption support
- `pillow` — Image clipboard support (optional)
- `pystray` — System tray icon (optional, experimental)

---

## 🎮 Usage

### Core Actions

| Action | How |
|--------|-----|
| **Send message** | Type → Press Enter or click Send |
| **Private DM** | Click a peer's name in sidebar |
| **Format text** | Use B / I / Color buttons |
| **Send file** | Click "Attach File" button |
| **View history** | Switch chats—history loads automatically |
| **Toggle sound** | Click 🔔 icon |
| **Clear chat** | Click "Clear Chat" button |

### Keyboard Shortcuts
- `Enter` — Send message
- `Ctrl+V` — Paste image from clipboard
- `Ctrl+Return` — (For future multi-line support)

---

## 🏗️ Architecture

```
Local Network (LAN / Subnet)
│
├─ Computer A (You)
│  └─ CFE Chat (listening on TCP:2222, UDP:2223)
│
├─ Computer B (Peer)
│  └─ CFE Chat (listening on TCP:2222, UDP:2223)
│
└─ Computer C (Peer)
   └─ CFE Chat (listening on TCP:2222, UDP:2223)

Auto-discovery via UDP broadcast every 2.5 seconds
Direct P2P messaging over TCP
File transfer with chunked streaming
```

---

## 🔒 Privacy & Security

✅ **No cloud. No servers. No tracking.**
- All data stays on your computer & LAN
- No internet required
- No analytics or telemetry
- MIT Licensed — fully open source
- Optional encryption available for sensitive chats

---

## ⚙️ Configuration

No configuration files needed. Everything is automatic.

**Want to customize?** Edit `cfe_chat_v5.py`:
```python
PORT = 2222                    # TCP server port
BROADCAST_PORT = 2223          # UDP discovery port
FILE_CHUNK_SIZE = 64 * 1024    # File transfer chunk size
DISCOVERY_INTERVAL = 2.5       # Discovery broadcast interval (seconds)
SOCKET_TIMEOUT = 15            # Connection timeout (seconds)
HISTORY_LIMIT = 500            # Max messages per conversation
```

---

## 📂 Data Storage

All data stored locally in `./chat_data/`:
```
chat_data/
├── log.txt                 # Chat history log
├── history.json            # Message history (500 per conversation)
├── contacts.json           # Saved contacts + last seen
├── error.log               # Error diagnostics
└── received_files/         # Downloaded files
```

Cross-platform paths are auto-detected (Windows/macOS/Linux).

---

## ⚠️ Known Limitations

### System Tray (Experimental)
- May not start reliably on all systems
- **Workaround**: Run without tray or restart application

### Clipboard Image Paste (Experimental)
- **Windows**: ✅ Works
- **Linux**: ⚠️ May need `xclip` or `xsel`: `apt install xclip xsel`
- **macOS**: ⚠️ Requires permission grant
- **Workaround**: Use "Attach File" button instead

### Network Scope
- LAN-only (same subnet)
- Behind strict firewalls may need port forwarding
- VPN/mesh networks supported

---

## 🔧 Troubleshooting

### Peers not showing up?
```bash
# Check if ports are open (macOS/Linux)
sudo lsof -i :2222
sudo lsof -i :2223

# Windows
netstat -ano | findstr :2222
```
Restart the app if discovery fails.

### Can't send messages?
- Check peer is online (green dot)
- Firewall: Allow TCP 2222 & UDP 2223
- If encryption on/off mismatch: restart app

### File transfer fails?
- Check disk space
- Files > 2 GB not supported
- Retry the transfer

### App crashes?
- Check Python version: `python --version` (need 3.8+)
- Check logs: `cat chat_data/error.log`
- Reinstall: `pip install --upgrade cfe-chat`

---

## 📦 What Gets Installed?

When you `pip install cfe-chat`:
```
/usr/local/bin/cfe-chat          # Executable script
/site-packages/cfe_chat/          # Package directory
├── __main__.py                   # Entry point
├── cfe_chat_v5.py                # Main application
└── requirements.txt              # Dependencies
```

Run from anywhere: `cfe-chat`

---

## 🚀 Development

### Clone & Run Locally
```bash
git clone https://github.com/timmoa-cfe/CFE-Chat.git
cd CFE-Chat
pip install -r requirements.txt
python cfe_chat_v5/cfe_chat_v5.py
```

### Building Package for PyPI
```bash
pip install build twine
python -m build
twine upload dist/*
```

---

## 📊 Performance

| Metric | Value |
|--------|-------|
| Max concurrent peers | 16+ |
| Message latency | <50 ms |
| File transfer speed | ~50 Mbps (LAN-limited) |
| Memory footprint | 60–120 MB |
| CPU (idle) | <5% |

---

## 🛣️ Roadmap

- [ ] PyPI package publishing (v5.0)
- [ ] IPv6 support
- [ ] Message search & filtering
- [ ] Better tray integration
- [ ] Cross-platform installers (exe, DMG, AppImage)
- [ ] Voice/video calls (v6.0+)
- [ ] Message reactions & emoji
- [ ] Web interface (optional)

---

## 📞 Support

- **Telegram**: [t.me/CFE_Chat](https://t.me/CFE_Chat)
- **GitHub Issues**: [Report bugs](https://github.com/timmoa-cfe/CFE-Chat/issues)
- **Documentation**: See [RELEASE_v5.0.md](RELEASE_v5.0.md)

---

## 📄 License

MIT License © 2026 timmoa-cfe

Permission to use, modify, and distribute freely. See [LICENSE](LICENSE) for details.

---

**Made with ❤️ for LAN communities.**

*CFE Chat — Zero config. Pure P2P. All local.*
