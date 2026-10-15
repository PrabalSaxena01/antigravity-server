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

## File Overview

* **`standalone_server.py`**: Zero-dependency standard library server. Runs on ANY Python version (including Python 3.14) without `pip install`.
* **`run.py`**: Cross-platform launcher with auto-detection for Python 3.14 and automated Cloudflare HTTPS tunnel.
* **`db.py`**: SQLite database layer for user auth, apps, rate limiting, and approval workflows.
* **`web_ui.py`**: Interactive Web Console dashboard.
* **`antigravity_gateway.py`**: FastAPI enterprise gateway (for systems with FastAPI & Pydantic).
* **`commands.txt`**: Quick reference cheat sheet for Android Termux.
