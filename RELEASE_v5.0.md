# 🚀 CFE Chat v5.0 — Decentralized P2P LAN Messenger

> **A fully autonomous, serverless peer-to-peer desktop chat application for isolated local networks.** Zero configuration. Zero external dependencies. Wire-to-wire communication over standard TCP/UDP sockets.

---

## ✨ What's Inside

### 🔗 Core Networking
- **Zero-Configuration Auto-Discovery** — UDP broadcast peer detection. No config files, no server setup.
- **Thread-Safe Backend** — Decoupled networking via ThreadPoolExecutor. GUI stays responsive.
- **TCP/UDP Sockets** — Direct P2P connection. Strictly LAN-bound. No internet required.
- **Keep-Alive & Ping/Pong** — Real-time connection quality (RTT ms) per peer.

### 💬 Messaging
- **Shared Room Chat** — Everyone on the LAN sees broadcast messages.
- **Private Direct Messages** — Encrypted DM channels with individual peers.
- **Persistent History** — Auto-logged message history (500 per conversation, JSON-backed).
- **Typing Indicators** — Real-time "X is typing…" notifications.
- **Message Formatting**
  - **Bold** & *Italic* text styling
  - Custom text colors via color picker
  - Sent/received message bubbles with timestamps

### 📁 File Sharing
- **High-Speed Chunked Transfers** — 64 KB chunks for efficient streaming.
- **Dynamic Progress Bars** — Real-time % upload/download tracking.
- **Auto-Download Folder** — Received files go to `~/Downloads` (configurable).
- **File Validation** — Size limits (max 2 GB). Safe filename handling.

### 🔐 Security
- **Optional Fernet Encryption** — Shared-secret AES encryption for messages.
- **Deterministic Key Derivation** — SHA-256 based from user password.
- **Graceful Fallback** — Encryption disabled if cryptography lib unavailable.

### 🎨 User Interface
- **CustomTkinter Dark GUI** — High-density, modern design.
- **Responsive Layout** — Sidebar with contact list. Full-width chat area.
- **Online/Offline Status** — Green dot (online) / Red dot (offline) per peer.
- **Contacts List** — Persists people you've chatted with. Last seen timestamp.
- **Sound Notifications** — Message alerts (toggle on/off). Title bar flash.
- **Quick Actions**
  - Attach File button
  - Telegram channel link
  - Clear chat history
  - Folder browser for downloads
  - Sound toggle

### 💾 Persistence
- **Local Storage** — All data in `./chat_data/` directory.
  - `log.txt` — Chat history log
  - `history.json` — Conversation history (500 msgs per chat)
  - `contacts.json` — Saved contacts with last seen
  - `error.log` — Error diagnostics
- **Auto-Save** — History & contacts written on every message.

---

## 🛠 Installation & Setup

### Prerequisites
- **Python 3.13+** (works with 3.8+ with minor tweaks)
- **pip** package manager

### Quick Start

#### 1. Clone the repository
```bash
git clone https://github.com/timmoa-cfe/CFE-Chat.git
cd CFE-Chat
```

#### 2. Install dependencies
```bash
pip install customtkinter cryptography pillow
```

**Optional** (for system tray support — currently experimental):
```bash
pip install pystray
```

#### 3. Run the application
```bash
python3 cfe_chat_v5/cfe_chat_v5.py
```

#### 4. First Launch
1. **Enter your nickname** (displayed in chat)
2. **Set a shared encryption secret** (optional, leave blank to skip)
3. Application auto-discovers peers on your LAN

---

## 🎮 How to Use

### Sending Messages
- Type in the input box
- Press **Enter** or click **Send**
- Use Ctrl+Return for multi-line support

### Formatting
- Click **B** for **Bold** text
- Click **I** for *Italic* text
- Click **A Color** to pick a custom text color

### File Sharing
1. Click **Attach File**
2. Select a file
3. Confirm the recipient (peer or everyone)
4. Monitor progress bar
5. Recipient auto-downloads to `~/Downloads`

### Contacts
- Chat with any online peer—they automatically appear in your **Contacts** sidebar
- **Green dot** = Online now | **Red dot** = Last seen (saved)
- Click RTT value to see connection quality (latency in ms)

### Private DMs
- Click a peer's name in the sidebar
- Chat header shows their IP & status
- Only they see your messages

### Room Chat
- Click **Room** button
- All online peers see your broadcast message

### Additional Controls
- **Clear Chat** — Delete history for current conversation
- **📁** — Open received files folder
- **🔔** — Toggle notification sounds
- **Telegram** — Jump to project's Telegram channel
- **Right-click** — Copy message text or IP address

---

## ⚙️ Configuration

### Environment Variables / Runtime Options
None required. Everything is auto-configured.

### Constants (if you want to tweak)
Edit `cfe_chat_v5.py` top section:
```python
PORT = 2222                    # TCP server port
BROADCAST_PORT = 2223          # UDP discovery port
FILE_CHUNK_SIZE = 64 * 1024    # File transfer chunk size
DISCOVERY_INTERVAL = 2.5       # Seconds between discovery broadcasts
SOCKET_TIMEOUT = 15            # Connection timeout (seconds)
HISTORY_LIMIT = 500            # Max messages per conversation
```

---

## 🔄 Architecture

```
┌─────────────────────────────────────────┐
│          CustomTkinter GUI              │
│  (Responsive, non-blocking message loop)│
└────────────────────┬────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
┌──────────────────┐    ┌──────────────────┐
│  TCP Server      │    │  UDP Broadcast   │
│  (Port 2222)     │    │  Listener        │
│  Handles         │    │  (Port 2223)     │
│  incoming DMs,   │    │  Auto-discovers  │
│  files, pings    │    │  new peers       │
└──────────────────┘    └──────────────────┘
        │                         │
        └────────────┬────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
┌──────────────────┐    ┌──────────────────┐
│  Thread Pool     │    │  Message Queue   │
│  (14 workers)    │    │  (Thread-safe)   │
│  Handles all     │    │  Decouples net   │
│  network I/O     │    │  from GUI        │
└──────────────────┘    └──────────────────┘
        │
        ▼
┌──────────────────┐
│  Peer Connections│
│  (IP → Socket)   │
│  Keep-alive pings│
└──────────────────┘
```

---

## 📋 Known Limitations & Notes

### ⚠️ System Tray Integration
- **Status**: Experimental (requires `pystray` + `pillow`)
- Currently may not start reliably on all systems
- Workaround: Run without tray support—just close to minimize

### 📸 Clipboard Image Paste (Ctrl+V)
- **Status**: Experimental (requires `pillow` + `PIL.ImageGrab`)
- **Platform-specific issues**:
  - ✅ Windows: Works reliably
  - ⚠️ Linux: May require additional system libraries (xclip, xsel)
  - ⚠️ macOS: Requires native permission grants
- If clipboard paste fails silently, manually use **Attach File** instead

### Network Scope
- **LAN-only** — Works on same subnet only
- To chat across subnets, use a VPN or mesh network overlay
- Peer detection uses broadcast—may not work behind strict firewalls

### File Size Limits
- Hard cap: **2 GB per file**
- Soft limit: Limited by available disk space

---

## 🔒 Privacy & Security

- **No Cloud** — Zero data leaves your network
- **No Analytics** — No telemetry, no phone-home
- **No Accounts** — Nicknames are local only
- **Encryption Optional** — Use shared secret for encrypted room
- **MIT License** — Open source, audit-friendly

---

## 🚀 Performance

| Metric | Value |
|--------|-------|
| Max concurrent peers | 16+ (thread pool limited to 14 workers) |
| Message latency | <50 ms on local 100 Mbps LAN |
| File transfer | ~50 Mbps typical (LAN speed limited) |
| Memory footprint | ~60–120 MB (GUI + Python runtime) |
| CPU usage | <5% idle, spikes during file transfer |

---

## 🔧 Troubleshooting

### No peers discovered
- **Check network**: Is everyone on the same subnet?
- **Firewall**: Allow ports 2222 (TCP) and 2223 (UDP)
- **Restart app**: Kill and relaunch the application

### Messages not sending
- **Check connection**: Peer must be online (green dot)
- **Check firewall**: Ensure TCP 2222 is open
- **Encryption mismatch**: If one user has encryption on and another off, messages won't decrypt properly

### File transfer fails
- **Check disk space**: Receiver must have enough space in `chat_data/received_files/`
- **Check file size**: Files >2 GB are rejected
- **Retry**: Network glitches can interrupt transfers

### Application crashes
- **Check Python version**: Requires 3.8+
- **Check dependencies**: Run `pip install -r requirements.txt`
- **Check logs**: See `chat_data/error.log`

---

## 📦 Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| **customtkinter** | Latest | GUI framework |
| **cryptography** | Latest | Fernet encryption (optional) |
| **pillow** | Latest | Image clipboard support (optional) |
| **pystray** | Latest | System tray icon (optional, experimental) |
| **Python stdlib** | 3.13+ | socket, threading, queue, json, etc. |

---

## 📞 Support & Community

- **Telegram**: [t.me/CFE_Chat](https://t.me/CFE_Chat)
- **GitHub Issues**: [Report bugs](https://github.com/timmoa-cfe/CFE-Chat/issues)
- **License**: MIT — fork & modify freely

---

## 🎯 Roadmap

- [ ] IPv6 support
- [ ] Message search & filtering
- [ ] Voice/video calls (future major version)
- [ ] Better tray integration
- [ ] Cross-platform package (exe, DMG, AppImage)
- [ ] Desktop shortcuts
- [ ] Message reactions & emoji support

---

## 📄 License

MIT License © 2026 timmoa-cfe. See [LICENSE](LICENSE) file for details.

---

**Made with ❤️ for LAN communities.**  
*CFE Chat v5.0 — Zero config. Pure P2P. All local.*
