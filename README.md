# Antigravity Multi-Tenant API Server

Turn any device (PC, laptop, workstation, or Android phone) into an API server for Antigravity AI.

## Quick Start on Android (Termux)

See [`commands.txt`](commands.txt) for exact copy-pasteable terminal commands.

### 1. Copy into Termux Home Directory
```bash
cp -r /sdcard/Download/antigravity_server ~/
cd ~/antigravity_server
```

### 2. Start the Server (Zero-Dependency Mode)
Works directly on **Python 3.14+** without requiring Rust, Pydantic, or any external compiler:

```bash
python standalone_server.py
```

Or run the auto-detecting launcher:
```bash
python run.py
```

### 3. Open Web Dashboard
* Local phone browser: `http://localhost:8000`
* Other devices on Wi-Fi: `http://<PHONE_IP>:8000`

---

## Quick Start on PC / Mac / Linux

### Windows:
Double-click `start.bat` or run:
```powershell
python run.py
```

### Mac / Linux:
```bash
bash start.sh
```

---

## Security & Virtual Middleware Architecture

* **🛡️ Safe Keyless Virtual Middleware (`/p/{public_slug}/v1`)**:
  Allows frontend clients (React, Next.js, mobile APKs) to invoke completions **without exposing secret API keys**. High-entropy 128-bit public slugs (`pub_...`) protect the route from enumeration.
* **🌐 CORS Domain Whitelisting**:
  Lock each App down to specific allowed origins (e.g. `https://myportfolio.com`). Unauthorized domains are blocked with `403 Forbidden`.
* **🔒 Subprocess Lifetime & Path Traversal Shielding**:
  All conversation IDs are strictly sanitized (`^[a-zA-Z0-9_\-]{4,128}$`) to block directory traversal attacks (`../`). Background subprocesses are automatically terminated on client disconnect to prevent CPU and battery drain.
* **⚡ DoS & Payload Limiting**:
  Strict 2 MB max body limit protects the server from memory exhaustion.
* **🔑 PBKDF2 Password Hashing & IP Brute-Force Rate Limiting**:
  100,000 rounds of PBKDF2-HMAC-SHA256 with constant-time verification. Login attempts are rate-limited per IP.
* **0 Initial Apps / Clean Slate**:
  Starts with 0 apps. Create isolated profiles per project with dedicated RPM limits and daily token quotas.

---

## File Overview

* **`standalone_server.py`**: Zero-dependency standard library server. Runs on ANY Python version (including Python 3.14) without `pip install`.
* **`run.py`**: Cross-platform launcher with auto-detection for Python 3.14 and automated Cloudflare HTTPS tunnel.
* **`db.py`**: Hardened SQLite database layer (PBKDF2, virtual middleware, sliding-window rate limiting).
* **`web_ui.py`**: Interactive Web Console dashboard with 1-click Admin login and middleware generators.
* **`antigravity_gateway.py`**: FastAPI enterprise gateway with matching virtual middleware routes.
* **`commands.txt`**: Quick reference cheat sheet for Android Termux.
