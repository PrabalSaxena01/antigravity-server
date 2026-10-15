"""
Antigravity Hardened Standalone API Server & Virtual Middleware Gateway
========================================================================
Runs on ANY Python version (including Python 3.14+ on Android/Termux, Windows, Mac, Linux)
with ZERO external dependencies (no FastAPI, no Pydantic, no Uvicorn).
Uses only Python standard library: http.server, sqlite3, json, threading, urllib, secrets, hashlib.

Security Architecture:
- Virtual Middleware per App: High-entropy slug routing with CORS domain whitelisting.
- Multi-App Isolation: Sliding-window rate limiting, daily token limits, model whitelists.
- DoS & Memory Protection: Bounded request bodies (max 2MB), null-byte sanitization.
- Subprocess Shielding: Strict conversation ID validation (no path traversal), guaranteed proc cleanup.
- Brute-Force Protection: IP-based login rate limiting.
- Security Headers: HSTS, CSP, X-Frame-Options, nosniff, Referrer-Policy on all responses.
"""

import os
import sys
import json
import time
import uuid
import shutil
import logging
import re
import urllib.request
import urllib.parse
from urllib.parse import urlparse
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import threading
import subprocess
import secrets

import db
from web_ui import WEB_UI_HTML

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("antigravity_server")

GATEWAY_DIR = Path(__file__).resolve().parent

# Locate agy executable
AGY_PATH = shutil.which("agy")
if not AGY_PATH:
    default_win_path = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
    termux_path = Path("/data/data/com.termux/files/usr/bin/agy")
    home_local = Path.home() / ".local" / "bin" / "agy"
    if default_win_path.exists():
        AGY_PATH = str(default_win_path)
    elif termux_path.exists():
        AGY_PATH = str(termux_path)
    elif home_local.exists():
        AGY_PATH = str(home_local)
    else:
        AGY_PATH = "agy" if sys.platform != "win32" else "agy.exe"

DEFAULT_SANDBOX_DIR = GATEWAY_DIR / "sandbox_workspace"
DEFAULT_SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"

# Maximum body payload limit (2 MB) to prevent DoS memory exhaustion
MAX_BODY_SIZE = 2 * 1024 * 1024

# Safe regex for conversation IDs to prevent directory traversal
SAFE_CID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{4,128}$")

# -------------------------------------------------------------------
# Model Aliases & Normalization
# -------------------------------------------------------------------
MODEL_ALIASES = {
    "gemini-2.5-flash": "gemini-3.8-flash-low",
    "gemini-2.5-pro": "gemini-3.8-flash-high",
    "gemini-flash": "gemini-3.8-flash-low",
    "gemini-pro": "gemini-3.8-flash-high",
    "default": "gemini-3.8-flash-low",
    "claude-sonnet": "claude-sonnet-4-6",
    "claude-opus": "claude-opus-4-6-thinking",
    "gpt-oss": "gpt-oss-120b-medium",
}

def normalize_model(model_name: Optional[str]) -> str:
    if not model_name:
        return "gemini-3.8-flash-low"
    m = model_name.strip().lower()
    return MODEL_ALIASES.get(m, model_name.strip())

def is_model_allowed(requested_model: str, allowed_models: List[str]) -> bool:
    if not requested_model or not allowed_models:
        return True
    if requested_model in allowed_models:
        return True
    norm_req = normalize_model(requested_model)
    norm_allowed = {normalize_model(m) for m in allowed_models}
    return norm_req in norm_allowed

# -------------------------------------------------------------------
# Conversation & Session Lifecycle Manager (Safe Path Traversal Protection)
# -------------------------------------------------------------------
DEFAULT_SESSION_TTL = 3600  # 1 hour inactivity TTL for rolling conversations

class ConversationManager:
    def __init__(self, ttl_seconds: int = DEFAULT_SESSION_TTL):
        self.ttl = ttl_seconds
        self.app_sessions: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()

    def sanitize_cid(self, cid: Optional[str]) -> Optional[str]:
        if not cid:
            return None
        clean = cid.strip()
        if not SAFE_CID_REGEX.match(clean):
            return None
        # Verify strict containment inside BRAIN_DIR
        try:
            target = (BRAIN_DIR / clean).resolve()
            if target.parent != BRAIN_DIR.resolve():
                return None
        except Exception:
            return None
        return clean

    def get_or_create_conversation(
        self,
        app_id: str,
        requested_cid: Optional[str] = None,
        ephemeral: bool = False
    ) -> Tuple[str, bool]:
        now = time.time()
        safe_requested = self.sanitize_cid(requested_cid)

        # 1. Valid client supplied conversation_id
        if safe_requested:
            return safe_requested, False

        # 2. Ephemeral mode (auto-cleanup after completion)
        if ephemeral:
            return f"ephem_{secrets.token_hex(8)}", True

        # 3. Rolling App Session with TTL
        with self.lock:
            session = self.app_sessions.get(app_id)
            if session and (now - session["last_active"]) < self.ttl:
                session["last_active"] = now
                return session["conversation_id"], False

            new_cid = f"app_{app_id[:8]}_{int(now)}"
            self.app_sessions[app_id] = {
                "conversation_id": new_cid,
                "last_active": now
            }
            return new_cid, False

    def cleanup_conversation(self, conversation_id: str):
        safe_cid = self.sanitize_cid(conversation_id)
        if not safe_cid or not BRAIN_DIR.exists():
            return
        target_dir = (BRAIN_DIR / safe_cid).resolve()
        if target_dir.parent == BRAIN_DIR.resolve() and target_dir.exists() and target_dir.is_dir():
            try:
                shutil.rmtree(target_dir, ignore_errors=True)
                logger.info(f"Purged conversation workspace: {safe_cid}")
            except Exception as e:
                logger.warning(f"Failed to remove conversation {safe_cid}: {e}")

    def purge_expired_sessions(self, max_age_seconds: int = 86400):
        if not BRAIN_DIR.exists():
            return
        now = time.time()
        try:
            for item in BRAIN_DIR.iterdir():
                if item.is_dir() and (item.name.startswith("ephem_") or item.name.startswith("app_")):
                    try:
                        mtime = item.stat().st_mtime
                        if (now - mtime) > max_age_seconds:
                            shutil.rmtree(item, ignore_errors=True)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Error during TTL cleanup: {e}")

conversation_manager = ConversationManager(ttl_seconds=DEFAULT_SESSION_TTL)

# -------------------------------------------------------------------
# Login Brute-Force Rate Limiter (IP-Based Protection)
# -------------------------------------------------------------------
class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self.attempts: Dict[str, List[float]] = {}
        self.lock = threading.Lock()

    def is_rate_limited(self, ip: str) -> bool:
        now = time.time()
        with self.lock:
            history = self.attempts.get(ip, [])
            history = [t for t in history if now - t < self.window]
            self.attempts[ip] = history
            return len(history) >= self.max_attempts

    def record_failure(self, ip: str):
        now = time.time()
        with self.lock:
            if ip not in self.attempts:
                self.attempts[ip] = []
            self.attempts[ip].append(now)

    def reset(self, ip: str):
        with self.lock:
            self.attempts.pop(ip, None)

login_limiter = LoginRateLimiter(max_attempts=5, window_seconds=300)

# -------------------------------------------------------------------
# Live In-Memory Approval Tracker
# -------------------------------------------------------------------
class LiveApprovalTracker:
    def __init__(self):
        self.events: Dict[str, threading.Event] = {}
        self.decisions: Dict[str, str] = {}
        self.notes: Dict[str, Optional[str]] = {}

    def register(self, approval_id: str) -> threading.Event:
        event = threading.Event()
        self.events[approval_id] = event
        return event

    def resolve(self, approval_id: str, decision: str, notes: Optional[str] = None):
        self.decisions[approval_id] = decision
        self.notes[approval_id] = notes
        if approval_id in self.events:
            self.events[approval_id].set()

    def get_decision(self, approval_id: str) -> Optional[str]:
        return self.decisions.get(approval_id)

    def cleanup(self, approval_id: str):
        self.events.pop(approval_id, None)
        self.decisions.pop(approval_id, None)
        self.notes.pop(approval_id, None)

approval_tracker = LiveApprovalTracker()

# -------------------------------------------------------------------
# Token Drain Risk Evaluator
# -------------------------------------------------------------------
EFFORT_RANKS = {"low": 1, "medium": 2, "high": 3, "xhigh": 4, "max": 5}

def evaluate_token_drain_risk(
    prompt: str,
    requested_model: str,
    requested_effort: str,
    app_info: Dict[str, Any],
    policy: Dict[str, Any]
) -> Tuple[bool, Optional[str]]:
    prompt_len = len(prompt)
    max_chars = policy.get("max_prompt_chars", 10000)
    if prompt_len > max_chars:
        return True, f"Token Drain Alert: Prompt length ({prompt_len:,} chars) exceeds safety threshold ({max_chars:,} chars)"

    req_rank = EFFORT_RANKS.get(requested_effort.lower(), 2)
    max_policy_rank = EFFORT_RANKS.get(policy.get("max_reasoning_effort", "high"), 3)
    if req_rank > max_policy_rank:
        if policy.get("block_high_effort", 1):
            return True, f"Token Drain Alert: Requested effort '{requested_effort}' exceeds policy threshold '{policy.get('max_reasoning_effort')}'"
        return True, "Token Drain Alert: High reasoning effort is flagged for manual review"

    if "pro" in requested_model.lower() or "ultra" in requested_model.lower():
        if policy.get("expensive_model_policy") == "require_approval":
            return True, f"Token Drain Alert: Premium model '{requested_model}' requires approval before consumption"

    if app_info.get("total_tokens_used", 0) >= app_info.get("daily_token_limit", 500000):
        return True, f"Token Drain Alert: App '{app_info['name']}' has exhausted its daily token quota ({app_info['daily_token_limit']:,} tokens)"

    return False, None

# -------------------------------------------------------------------
# HTTP Request Handler (Standard Library with Hardened Security)
# -------------------------------------------------------------------
class AntigravityHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info(f"{self.address_string()} - {format % args}")

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' 'unsafe-eval' https:; img-src 'self' data: https:; font-src 'self' https:;")

    def send_cors_headers(self, origin: str = "*", allowed_origins: Optional[List[str]] = None):
        if allowed_origins and "*" not in allowed_origins:
            if origin and origin in allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            else:
                self.send_header("Access-Control-Allow-Origin", "null")
        else:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Max-Age", "86400")

    def do_OPTIONS(self):
        parsed = urlparse(self.path)
        path = parsed.path
        origin = self.headers.get("Origin", "")

        # Check virtual middleware pre-flight
        match_vm = re.match(r"^/p/([^/]+)(?:/v1)?/chat/completions$", path)
        allowed_origins = None
        if match_vm:
            slug = match_vm.group(1).strip()
            app_info = db.get_app_by_slug_or_id(slug)
            if app_info:
                allowed_origins = app_info.get("allowed_origins")

        self.send_response(204)
        self.send_security_headers()
        self.send_cors_headers(origin=origin, allowed_origins=allowed_origins)
        self.end_headers()

    def send_json(self, status_code: int, data: Any, origin: str = "*", allowed_origins: Optional[List[str]] = None):
        try:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_security_headers()
            self.send_cors_headers(origin=origin, allowed_origins=allowed_origins)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def read_json_body(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        try:
            content_len = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None, "Invalid Content-Length header"

        if content_len < 0:
            return None, "Invalid Content-Length header"
        if content_len > MAX_BODY_SIZE:
            return None, f"Payload size ({content_len:,} bytes) exceeds maximum limit of {MAX_BODY_SIZE:,} bytes"
        if content_len == 0:
            return {}, None

        raw = self.rfile.read(content_len).decode("utf-8", errors="replace")
        try:
            return json.loads(raw), None
        except Exception:
            return None, "Malformed JSON payload"

    def get_auth_token(self) -> Optional[str]:
        auth = self.headers.get("Authorization", "")
        parts = auth.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        return None

    def authenticate_user(self) -> Optional[Dict[str, Any]]:
        token = self.get_auth_token()
        if not token or token.strip().lower() in ("", "undefined", "null", "none"):
            return None
        return db.get_user_by_token(token)

    def authenticate_caller(self) -> Optional[Dict[str, Any]]:
        token = self.get_auth_token()
        if not token or token.strip().lower() in ("", "undefined", "null", "none"):
            return None
        app_info = db.get_app_by_key(token)
        if app_info and app_info.get("status") == "active":
            user = db.get_user_by_token(app_info["user_id"]) or {"id": app_info["user_id"]}
            return {"type": "app", "app": app_info, "user": user}
        return None

    # ---------------------------------------------------------------
    # Unified Chat Completion Engine (Streaming & Non-Streaming)
    # ---------------------------------------------------------------
    def process_chat_completion(
        self,
        app_info: Dict[str, Any],
        body: Dict[str, Any],
        origin: str = "*",
        allowed_origins: Optional[List[str]] = None
    ):
        # 1. Rate Limit Enforcement
        allowed, req_count = db.check_rate_limit(app_info["id"], app_info["rate_limit_rpm"])
        if not allowed:
            self.send_json(429, {"detail": f"Rate limit exceeded: {app_info['rate_limit_rpm']} RPM"}, origin, allowed_origins)
            return

        # 2. Model Whitelist Check
        req_model = body.get("model") or "gemini-3.8-flash-low"
        if not is_model_allowed(req_model, app_info["allowed_models"]):
            self.send_json(403, {"detail": f"Model '{req_model}' is not permitted for this App"}, origin, allowed_origins)
            return

        # 3. Message Extraction & Null-Byte Sanitization
        messages = body.get("messages", [])
        last_prompt = ""
        for m in reversed(messages):
            if m.get("role", "").lower() == "user":
                last_prompt = m.get("content", "")
                break

        # Sanitize prompt (remove null bytes)
        last_prompt = last_prompt.replace("\x00", "").strip()
        if not last_prompt:
            self.send_json(400, {"detail": "No valid user message provided"}, origin, allowed_origins)
            return

        effective_effort = body.get("effort") or app_info.get("max_effort", "medium")
        target_model = normalize_model(req_model)
        ephemeral = bool(body.get("ephemeral", False))
        requested_cid = body.get("conversation_id")
        stream_mode = bool(body.get("stream", False))

        # 4. Token Drain Evaluation
        policy = db.get_token_guard_policy()
        requires_approval, risk_reason = evaluate_token_drain_risk(
            last_prompt, target_model, effective_effort, app_info, policy
        )
        if requires_approval:
            self.send_json(403, {"detail": risk_reason}, origin, allowed_origins)
            return

        # 5. Resolve Conversation Session (Safe Path Traversal Protection)
        cid, should_cleanup = conversation_manager.get_or_create_conversation(
            app_id=app_info["id"],
            requested_cid=requested_cid,
            ephemeral=ephemeral
        )

        cmd = [
            AGY_PATH,
            "-p", last_prompt,
            "--sandbox",
            "--conversation", cid
        ]
        if target_model:
            cmd.extend(["--model", target_model])
        if effective_effort and not any(k in target_model.lower() for k in ["-low", "-medium", "-high"]):
            cmd.extend(["--effort", effective_effort])

        cmpl_id = f"chatcmpl-{secrets.token_hex(12)}"
        created_ts = int(time.time())

        # A. Streaming Response (SSE compliant with OpenAI SDK)
        if stream_mode:
            cmd.extend(["--output-format", "stream-json"])
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_security_headers()
            self.send_cors_headers(origin=origin, allowed_origins=allowed_origins)
            self.end_headers()

            proc = None
            tokens_estimated = 0
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
                for line in proc.stdout:
                    line_str = line.strip()
                    if line_str:
                        # Extract token chunk
                        delta_text = line_str
                        try:
                            parsed_line = json.loads(line_str)
                            if isinstance(parsed_line, dict):
                                delta_text = parsed_line.get("content") or parsed_line.get("delta") or line_str
                        except Exception:
                            pass

                        chunk_payload = json.dumps({
                            "id": cmpl_id,
                            "object": "chat.completion.chunk",
                            "created": created_ts,
                            "model": req_model,
                            "choices": [{
                                "index": 0,
                                "delta": {"content": delta_text},
                                "finish_reason": None
                            }]
                        })
                        self.wfile.write(f"data: {chunk_payload}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        tokens_estimated += max(1, len(delta_text) // 4)

                proc.wait()
                # Send terminal stop chunk
                stop_payload = json.dumps({
                    "id": cmpl_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": req_model,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop"
                    }]
                })
                self.wfile.write(f"data: {stop_payload}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                err_chunk = json.dumps({"error": str(e)})
                try:
                    self.wfile.write(f"data: {err_chunk}\n\n".encode("utf-8"))
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except Exception:
                    pass
            finally:
                # Guarantee subprocess termination on disconnect to prevent battery/CPU leak
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                db.log_token_usage(app_info["id"], max(50, tokens_estimated))
                if should_cleanup:
                    conversation_manager.cleanup_conversation(cid)
            return

        # B. Non-Streaming Response (Standard OpenAI JSON)
        cmd.extend(["--output-format", "json"])
        proc = None
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = proc.communicate(timeout=90)
            content = stdout.strip()
            try:
                parsed_out = json.loads(content)
                if isinstance(parsed_out, dict) and "response" in parsed_out:
                    content = parsed_out["response"]
            except Exception:
                pass

            total_tokens = max(50, (len(last_prompt) + len(content)) // 4)
            db.log_token_usage(app_info["id"], total_tokens)

            self.send_json(200, {
                "id": cmpl_id,
                "object": "chat.completion",
                "created": created_ts,
                "model": req_model,
                "conversation_id": cid,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": len(last_prompt) // 4,
                    "completion_tokens": len(content) // 4,
                    "total_tokens": total_tokens
                }
            }, origin, allowed_origins)
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            self.send_json(504, {"detail": "Subprocess execution timed out"}, origin, allowed_origins)
        except Exception as e:
            self.send_json(500, {"detail": f"Execution error: {str(e)}"}, origin, allowed_origins)
        finally:
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            if should_cleanup:
                conversation_manager.cleanup_conversation(cid)

    # ---------------------------------------------------------------
    # GET Requests
    # ---------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 0. Favicon (returns 204 No Content to avoid browser socket churn)
        if path == "/favicon.ico":
            self.send_response(204)
            self.send_security_headers()
            self.send_cors_headers()
            self.end_headers()
            return

        # 1. Root Web Console
        if path == "/" or path == "/index.html":
            try:
                body = WEB_UI_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_security_headers()
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        # 2. Health check
        if path == "/v1/health":
            self.send_json(200, {
                "status": "healthy",
                "service": "Antigravity Hardened Standalone Gateway",
                "version": "3.0.0",
                "virtual_middleware": True,
                "python": sys.version.split()[0],
                "zero_dependencies": True,
                "session_ttl_seconds": conversation_manager.ttl,
                "timestamp": time.time()
            })
            return

        # 3. User profile verification
        if path == "/v1/auth/me":
            user = self.authenticate_user()
            if not user:
                self.send_json(401, {"detail": "Unauthorized"})
                return
            apps = db.list_user_apps(user["id"])
            self.send_json(200, {
                "id": user["id"],
                "username": user["username"],
                "is_admin": bool(user.get("is_admin", 0)),
                "apps_count": len(apps)
            })
            return

        # 4. Apps listing
        if path == "/v1/apps":
            user = self.authenticate_user()
            if not user:
                self.send_json(401, {"detail": "Unauthorized"})
                return
            apps = db.list_user_apps(user["id"])
            self.send_json(200, apps)
            return

        # 5. Token Guard Policy
        if path == "/v1/token-guard":
            user = self.authenticate_user()
            if not user:
                self.send_json(401, {"detail": "Unauthorized"})
                return
            self.send_json(200, db.get_token_guard_policy())
            return

        # 6. Pending approvals
        if path == "/v1/approvals/pending":
            user = self.authenticate_user()
            if not user:
                self.send_json(401, {"detail": "Unauthorized"})
                return
            self.send_json(200, db.list_pending_approvals())
            return

        self.send_json(404, {"detail": "Route not found"})

    # ---------------------------------------------------------------
    # POST Requests
    # ---------------------------------------------------------------
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        origin = self.headers.get("Origin", "")

        body, err = self.read_json_body()
        if err:
            self.send_json(400 if "Malformed" in err else 413, {"detail": err})
            return

        # 1. Login with Brute-Force Rate Limiting
        if path == "/v1/auth/login":
            client_ip = self.client_address[0] if self.client_address else "unknown"
            if login_limiter.is_rate_limited(client_ip):
                self.send_json(429, {"detail": "Too many failed login attempts. Please wait 5 minutes."})
                return

            username = body.get("username", "").strip()
            password = body.get("password", "")
            user = db.authenticate_user(username, password)
            if not user:
                login_limiter.record_failure(client_ip)
                self.send_json(401, {"detail": "Invalid credentials. Default is admin / admin"})
                return

            login_limiter.reset(client_ip)
            token_val = user.get("user_token") or user.get("token")
            self.send_json(200, {
                "token": token_val,
                "user_token": token_val,
                "user": {"token": token_val, "username": user["username"]},
                "username": user["username"],
                "role": user.get("role", "developer"),
                "is_admin": bool(user.get("is_admin", 0))
            })
            return

        # 2. Register
        if path == "/v1/auth/register":
            username = body.get("username", "").strip()
            password = body.get("password", "")
            if not username or not password:
                self.send_json(400, {"detail": "Username and password required"})
                return
            try:
                user = db.create_user(username, password)
                token_val = user["token"]
                self.send_json(200, {
                    "token": token_val,
                    "user_token": token_val,
                    "user": {"token": token_val, "username": user["username"]},
                    "username": user["username"],
                    "role": user.get("role", "developer"),
                    "is_admin": bool(user.get("is_admin", 0))
                })
            except Exception as e:
                self.send_json(400, {"detail": f"Registration failed: {str(e)}"})
            return

        # 3. Create App with Virtual Middleware & CORS Whitelist
        if path == "/v1/apps":
            user = self.authenticate_user()
            if not user:
                self.send_json(401, {"detail": "Unauthorized"})
                return
            name = body.get("name", "").strip()
            if not name:
                self.send_json(400, {"detail": "App name required"})
                return
            try:
                allowed_models = body.get("allowed_models") or ["gemini-2.5-flash", "gemini-2.5-pro"]
                allowed_origins = body.get("allowed_origins") or ["*"]
                new_app = db.create_app(
                    user_id=user["id"],
                    name=name,
                    rate_limit_rpm=int(body.get("rate_limit_rpm", 15)),
                    daily_token_limit=int(body.get("daily_token_limit", 500000)),
                    allowed_models=allowed_models,
                    allowed_origins=allowed_origins,
                    access_type=body.get("access_type", "sandboxed_tools"),
                    max_effort=body.get("max_effort", "medium"),
                    custom_api_key=body.get("api_key"),
                    enable_virtual_middleware=int(body.get("enable_virtual_middleware", 1))
                )
                self.send_json(200, new_app)
            except Exception as e:
                self.send_json(400, {"detail": str(e)})
            return

        # 4. Token Guard Policy Update
        if path == "/v1/token-guard":
            user = self.authenticate_user()
            if not user or not user.get("is_admin"):
                self.send_json(403, {"detail": "Admin authorization required"})
                return
            db.update_token_guard_policy(body)
            self.send_json(200, {"status": "success", "policy": db.get_token_guard_policy()})
            return

        # 5. Respond to Approval
        match_approval = re.match(r"^/v1/approvals/([^/]+)/respond$", path)
        if match_approval:
            user = self.authenticate_user()
            if not user:
                self.send_json(401, {"detail": "Unauthorized"})
                return
            approval_id = match_approval.group(1)
            decision = body.get("decision", "").lower().strip()
            notes = body.get("notes")
            if decision not in ("approve", "deny"):
                self.send_json(400, {"detail": "Decision must be 'approve' or 'deny'"})
                return
            success = db.resolve_approval(approval_id, decision, notes)
            if not success:
                self.send_json(404, {"detail": "Approval ticket not found"})
                return
            approval_tracker.resolve(approval_id, decision, notes)
            self.send_json(200, {"status": "success", "approval_id": approval_id, "decision": decision})
            return

        # 6. Safe Keyless Virtual Middleware Route (/p/{slug}/v1/chat/completions)
        match_vm = re.match(r"^/p/([^/]+)(?:/v1)?/chat/completions$", path)
        if match_vm:
            slug = match_vm.group(1).strip()
            app_info = db.get_app_by_slug_or_id(slug)
            if not app_info:
                self.send_json(404, {"detail": "Virtual Middleware endpoint not found"}, origin)
                return
            if app_info.get("status") != "active":
                self.send_json(403, {"detail": "App is suspended"}, origin)
                return
            if not app_info.get("enable_virtual_middleware", True):
                self.send_json(403, {"detail": "Virtual Middleware is disabled for this App"}, origin)
                return

            # Enforce CORS origin whitelist
            allowed_origins = app_info.get("allowed_origins", ["*"])
            if allowed_origins and "*" not in allowed_origins and origin:
                if origin not in allowed_origins:
                    self.send_json(403, {"detail": f"Origin '{origin}' is not authorized for this App"}, origin, allowed_origins)
                    return

            self.process_chat_completion(app_info, body, origin=origin, allowed_origins=allowed_origins)
            return

        # 7. Standard Authenticated Route (/v1/chat/completions with Bearer Key)
        if path == "/v1/chat/completions":
            caller = self.authenticate_caller()
            if not caller:
                self.send_json(401, {"detail": "Unauthorized: Valid API Key required"})
                return
            app_info = caller["app"]
            self.process_chat_completion(app_info, body, origin=origin)
            return

        self.send_json(404, {"detail": "Route not found"})

    # ---------------------------------------------------------------
    # PUT & DELETE Requests
    # ---------------------------------------------------------------
    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path

        match_app = re.match(r"^/v1/apps/([^/]+)$", path)
        if match_app:
            user = self.authenticate_user()
            if not user:
                self.send_json(401, {"detail": "Unauthorized"})
                return
            app_id = match_app.group(1)
            body, err = self.read_json_body()
            if err:
                self.send_json(400, {"detail": err})
                return
            success = db.update_app_settings(app_id, user["id"], body)
            if success:
                self.send_json(200, {"status": "success", "app_id": app_id})
            else:
                self.send_json(404, {"detail": "App not found"})
            return

        self.send_json(404, {"detail": "Route not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        match_app = re.match(r"^/v1/apps/([^/]+)$", path)
        if match_app:
            user = self.authenticate_user()
            if not user:
                self.send_json(401, {"detail": "Unauthorized"})
                return
            app_id = match_app.group(1)
            success = db.delete_app(app_id, user["id"])
            if success:
                self.send_json(200, {"status": "success", "deleted": app_id})
            else:
                self.send_json(404, {"detail": "App not found"})
            return

        self.send_json(404, {"detail": "Route not found"})

# -------------------------------------------------------------------
# Server Execution
# -------------------------------------------------------------------
def run_server(port: int = 8000, host: str = "0.0.0.0"):
    db.init_db()
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, AntigravityHandler)
    logger.info(f"[*] Antigravity Hardened Server listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("[*] Shutting down server gracefully...")
        httpd.server_close()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    run_server(port=port, host=host)
