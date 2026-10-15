"""
Antigravity Universal Server Launcher (Cross-Platform: Windows, Mac, Linux)
==========================================================================
Turn any personal computer into a secure Antigravity API Server with:
- Zero manual configuration: auto-checks dependencies and provisions Cloudflare Tunnel.
- Connects to your local Google Antigravity CLI login.
- Prints Local, Wi-Fi LAN, and Public HTTPS URLs.
- Graceful multi-process shutdown on Ctrl+C.
"""

import os
import sys
import time
import socket
import shutil
import urllib.request
import platform
import subprocess
import signal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Ensure Python version >= 3.8
if sys.version_info < (3, 8):
    print("[!] Python 3.8 or higher is required.")
    sys.exit(1)

def print_banner():
    banner = r"""
   ___          __  _                         _ __          
  / _ | ___  __/ /_(_)__ ________ __  _____ _(_) /___ __    
 / __ |/ _ \/ _  / / _ `/ __/ _ `/ / / / _ `/ / __/ // /    
/_/ |_/_//_/\_,_/_/\_, /_/  \_,_/\_/ /\_,_/_/\__/\_, /     
                  /___/                         /___/       
        --- Turn Your Device into an AI API Server ---
    """
    print(banner)

def get_lan_ip() -> str:
    """Discovers the local Wi-Fi / LAN IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def check_dependencies():
    """Checks and auto-installs FastAPI, Uvicorn, and Pydantic if missing. Uses standalone server on Python 3.14+."""
    if sys.version_info >= (3, 14):
        print("[i] Detected Python 3.14+ on this device.")
        print("[✓] Using Zero-Dependency Standalone Server (bypasses all Pydantic/Rust issues)!\n")
        return

    missing = []
    for pkg in ["fastapi", "uvicorn", "pydantic"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"[*] Installing required Python packages: {', '.join(missing)}...")
        req_file = BASE_DIR / "requirements.txt"
        if req_file.exists():
            cmd = [sys.executable, "-m", "pip", "install", "-r", str(req_file)]
        else:
            cmd = [sys.executable, "-m", "pip", "install", *missing]
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError:
            print("[!] Standard pip install failed (likely pydantic-core on Android).")
            print("[*] Installing Android Termux compatible packages (pydantic<2.0.0)...")
            fallback_cmd = [sys.executable, "-m", "pip", "install", "pydantic<2.0.0", "fastapi>=0.95.0", "uvicorn>=0.20.0"]
            subprocess.check_call(fallback_cmd)
        print("[+] Dependencies successfully installed!\n")

def check_antigravity_cli() -> str:
    """Checks for Google Antigravity CLI on the host."""
    agy_path = shutil.which("agy")
    if not agy_path and platform.system() == "Windows":
        default_win = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
        if default_win.exists():
            agy_path = str(default_win)

    if agy_path:
        print(f"[✓] Google Antigravity CLI found: {agy_path}")
        print("[✓] Using your device's authenticated Google Antigravity session.\n")
    else:
        print("[!] Antigravity CLI ('agy') not found on system PATH.")
        print("    You can still use mock/API endpoints. To install Antigravity CLI:")
        print("    Visit https://antigravity.google or run 'agy' once installed.\n")
    return agy_path or "agy"

def ensure_cloudflared() -> str:
    """Locates or downloads cloudflared standalone binary."""
    # Check PATH
    bin_path = shutil.which("cloudflared")
    if bin_path:
        return bin_path

    # Check common Windows path
    if platform.system() == "Windows":
        win_installed = Path("C:/Program Files (x86)/cloudflared/cloudflared.exe")
        if win_installed.exists():
            return str(win_installed)
        win_installed_64 = Path("C:/Program Files/cloudflared/cloudflared.exe")
        if win_installed_64.exists():
            return str(win_installed_64)

    # Local bin directory inside this package
    local_bin_dir = BASE_DIR / ".bin"
    local_bin_dir.mkdir(parents=True, exist_ok=True)
    local_exe = local_bin_dir / ("cloudflared.exe" if platform.system() == "Windows" else "cloudflared")

    if local_exe.exists():
        return str(local_exe)

    # Auto-download standalone executable based on OS & Arch
    system = platform.system().lower()
    machine = platform.machine().lower()
    print("[*] Downloading standalone Cloudflare Tunnel binary for one-click public HTTPS...")

    url = ""
    if system == "windows":
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    elif system == "darwin":  # macOS
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64" if "arm" in machine else "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64"
    elif system == "linux":
        if "arm" in machine or "aarch64" in machine:
            url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
        elif "armv7" in machine or "armhf" in machine:
            url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm"
        else:
            url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"

    if url:
        try:
            print(f"    Fetching {url}...")
            urllib.request.urlretrieve(url, str(local_exe))
            if system != "windows":
                os.chmod(str(local_exe), 0o755)
            print("[+] Cloudflare Tunnel binary downloaded!\n")
            return str(local_exe)
        except Exception as e:
            print(f"[!] Could not download cloudflared: {e}. Public tunnel will be disabled.")
            return ""

    return ""

def main():
    print_banner()
    check_dependencies()
    check_antigravity_cli()

    # Initialize Database
    try:
        import db
        db.init_db()
    except Exception as e:
        print(f"[!] Error initializing database: {e}")

    lan_ip = get_lan_ip()
    port = int(os.environ.get("PORT", "8000"))

    # 1. Start Server (FastAPI with Uvicorn, or Zero-Dependency Standalone for Python 3.14+ / Termux)
    use_standalone = sys.version_info >= (3, 14)
    if not use_standalone:
        try:
            import fastapi
            import pydantic
            import uvicorn
        except Exception:
            use_standalone = True

    server_env = os.environ.copy()
    server_env["PORT"] = str(port)
    server_env["HOST"] = "0.0.0.0"

    if use_standalone:
        print(f"[*] Starting Zero-Dependency Antigravity Server on 127.0.0.1:{port}...")
        server_cmd = [sys.executable, "standalone_server.py"]
    else:
        print(f"[*] Starting FastAPI Gateway on 127.0.0.1:{port}...")
        server_cmd = [sys.executable, "-m", "uvicorn", "antigravity_gateway:app", "--host", "0.0.0.0", "--port", str(port)]

    server_process = subprocess.Popen(
        server_cmd,
        cwd=str(BASE_DIR),
        env=server_env
    )

    # 2. Start Cloudflare Tunnel
    cloudflared_path = ensure_cloudflared()
    tunnel_process = None
    public_url = "Waiting for tunnel..."

    if cloudflared_path:
        print("[*] Starting Cloudflare Tunnel...")
        tunnel_log_path = BASE_DIR / "cloudflare_tunnel.log"
        log_file = open(tunnel_log_path, "w", encoding="utf-8")

        tunnel_process = subprocess.Popen(
            [cloudflared_path, "tunnel", "--url", f"http://127.0.0.1:{port}"],
            stderr=log_file,
            stdout=log_file,
            cwd=str(BASE_DIR)
        )

        # Wait up to 10 seconds to read the tunnel URL
        start_t = time.time()
        while time.time() - start_t < 12:
            time.sleep(1.5)
            if tunnel_log_path.exists():
                content = tunnel_log_path.read_text(encoding="utf-8", errors="replace")
                import re
                match = re.search(r"(https://[a-zA-Z0-9-]+\.trycloudflare\.com)", content)
                if match:
                    public_url = match.group(1)
                    break

    # 3. Print Connection Summary Card
    time.sleep(1)
    print("\n" + "="*68)
    print("      🎉 YOUR ANTIGRAVITY SERVER IS NOW RUNNING!")
    print("="*68)
    print(f"  🌐 Localhost Dashboard :  http://127.0.0.1:{port}")
    print(f"  🏠 Home Wi-Fi Dashboard:  http://{lan_ip}:{port}")
    if "trycloudflare.com" in public_url:
        print(f"  🌍 Public HTTPS URL    :  {public_url}")
    else:
        print(f"  🌍 Public HTTPS URL    :  {public_url} (Check cloudflare_tunnel.log)")
    print("-" * 68)
    print("  🔑 Initial Admin Login :")
    print("     Username : admin")
    print("     Password : AntigravityAdmin2026!")
    print("     (You can change your password anytime in the dashboard)")
    print("-" * 68)
    print("  📱 Connect From Android Termux:")
    if "trycloudflare.com" in public_url:
        print(f"     curl -s {public_url}/client.sh -o agy.sh && chmod +x agy.sh && ./agy.sh")
    else:
        print(f"     curl -s http://{lan_ip}:{port}/client.sh -o agy.sh && chmod +x agy.sh && ./agy.sh")
    print("="*68 + "\n")
    print("[*] Press Ctrl+C at any time to safely stop the server.\n")

    def signal_handler(sig, frame):
        print("\n[*] Shutting down Antigravity Server & Tunnel...")
        if tunnel_process:
            try:
                tunnel_process.terminate()
            except Exception:
                pass
        if server_process:
            try:
                server_process.terminate()
            except Exception:
                pass
        print("[+] Server stopped cleanly. Goodbye!")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Keep launcher alive
        server_process.wait()
    except KeyboardInterrupt:
        signal_handler(None, None)

if __name__ == "__main__":
    main()
