"""
Antigravity Zero-Dependency Standalone API Server
=================================================
Runs on ANY Python version (including Python 3.14+ on Android/Termux, Windows, Mac, Linux)
with ZERO external dependencies (no FastAPI, no Pydantic, no Uvicorn, no compilation required).
Uses only Python standard library: http.server, sqlite3, json, threading, urllib.

Features:
- Multi-App API Key Management with Model Selection & Rate Limits
- Rolling Sessions & TTL Conversation Cleanup (prevents creating a new chat on every API call)
- Web Console Dashboard (HTML/JS)
- OpenAI-compatible Completions & SSE Streaming API
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
# Conversation & Session Lifecycle Manager (TTL & Ephemeral Cleanup)
# -------------------------------------------------------------------
DEFAULT_SESSION_TTL = 3600  # 1 hour inactivity TTL for rolling conversations

class ConversationManager:
    """
    Prevents spawning a new chat on every API call.
    - If client provides conversation_id -> reuses that specific chat.
    - If client requests ephemeral/stateless -> generates temp ID and deletes folder from brain immediately.
    - Otherwise -> maintains a rolling App session with a TTL (default 1 hour).
    """
    def __init__(self, ttl_seconds: int = DEFAULT_SESSION_TTL):
        self.ttl = ttl_seconds
        self.app_sessions: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()

    def get_or_create_conversation(
        self,
        app_id: str,
        requested_cid: Optional[str] = None,
        ephemeral: bool = False
    ) -> Tuple[str, bool]:
        """Returns (conversation_id, should_cleanup_immediately)"""
        now = time.time()

        # 1. Client explicitly supplied conversation_id
        if requested_cid and requested_cid.strip():
            return requested_cid.strip(), False

        # 2. Ephemeral mode (one-shot query to be deleted after response)
        if ephemeral:
            return f"ephem_{uuid.uuid4().hex[:12]}", True

        # 3. Rolling App Session with TTL
        with self.lock:
            session = self.app_sessions.get(app_id)
            if session and (now - session["last_active"]) < self.ttl:
                session["last_active"] = now
                return session["conversation_id"], False

            # Session expired or doesn't exist -> start new rolling session
            new_cid = f"app_{app_id[:10]}_{int(now)}"
            self.app_sessions[app_id] = {
                "conversation_id": new_cid,
                "last_active": now
            }
            return new_cid, False

    def cleanup_conversation(self, conversation_id: str):
        """Immediately deletes the conversation folder from Antigravity brain storage."""
        if not BRAIN_DIR.exists():
            return
        target_dir = BRAIN_DIR / conversation_id
        if target_dir.exists() and target_dir.is_dir():
            try:
                shutil.rmtree(target_dir, ignore_errors=True)
                logger.info(f"Purged ephemeral conversation folder: {conversation_id}")
            except Exception as e:
                logger.warning(f"Failed to remove conversation {conversation_id}: {e}")

    def purge_expired_sessions(self, max_age_seconds: int = 86400):
        """Background cleaner that purges orphaned ephemeral/app sessions older than max_age."""
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
                            logger.info(f"TTL cleaner purged stale session: {item.name}")
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Error during TTL session cleanup: {e}")

conversation_manager = ConversationManager(ttl_seconds=DEFAULT_SESSION_TTL)

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
        return True, "Token Drain Alert: High reasoning effort is flagged for manual review by system administrator"

    if "pro" in requested_model.lower() or "ultra" in requested_model.lower():
        if policy.get("expensive_model_policy") == "require_approval":
            return True, f"Token Drain Alert: Premium model '{requested_model}' requires approval before consumption"

    if app_info.get("total_tokens_used", 0) >= app_info.get("daily_token_limit", 500000):
        return True, f"Token Drain Alert: App '{app_info['name']}' has exhausted its daily token quota ({app_info['daily_token_limit']:,} tokens)"

    return False, None

# -------------------------------------------------------------------
# HTTP Request Handler (Standard Library)
# -------------------------------------------------------------------
class AntigravityHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info(f"{self.address_string()} - {format % args}")

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def send_json(self, status_code: int, data: Any):
        try:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def read_json_body(self) -> Dict[str, Any]:
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            return {}
        raw = self.rfile.read(content_len).decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            return {}

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
        if app_info:
            if app_info["status"] != "active":
                return None
            user = db.get_user_by_token(app_info["user_id"]) or {"id": app_info["user_id"]}
            return {"type": "app", "app": app_info, "user": user}

        user = db.get_user_by_token(token)
        if user:
            apps = db.list_user_apps(user["id"])
            default_app = apps[0] if apps else db.create_app(user["id"], "Default Console App")
            return {"type": "user", "app": default_app, "user": user}
        return None

    # ---------------------------------------------------------------
    # GET Requests
    # ---------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 0. Favicon (returns 204 No Content to avoid browser socket churn)
        if path == "/favicon.ico":
            self.send_response(204)
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
                "service": "Antigravity Standalone Gateway",
                "version": "2.2.0",
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

        # 4. User profile / apps listing
        if path == "/v1/apps":
            user = self.authenticate_user()
            if not user:
                self.send_json(401, {"detail": "Unauthorized"})
                return
            apps = db.list_user_apps(user["id"])
            self.send_json(200, apps)
            return

        # 4. Token Guard Policy
        if path == "/v1/token-guard":
            user = self.authenticate_user()
            if not user:
                self.send_json(401, {"detail": "Unauthorized"})
                return
            self.send_json(200, db.get_token_guard_policy())
            return

        # 5. Pending approvals
        if path == "/v1/approvals/pending":
            user = self.authenticate_user()
            if not user:
                self.send_json(401, {"detail": "Unauthorized"})
                return
            self.send_json(200, db.list_pending_approvals(user["id"]))
            return

        self.send_json(404, {"detail": "Route not found"})

    # ---------------------------------------------------------------
    # POST Requests
    # ---------------------------------------------------------------
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self.read_json_body()

        # 1. Login
        if path == "/v1/auth/login":
            username = body.get("username", "").strip()
            password = body.get("password", "")
            user = db.authenticate_user(username, password)
            if not user:
                self.send_json(401, {"detail": "Invalid credentials. Default is admin / admin"})
                return
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
                self.send_json(200, {
                    "token": user["token"],
                    "user": {"token": user["token"], "username": user["username"]},
                    "username": user["username"],
                    "role": user.get("role", "developer"),
                    "is_admin": bool(user.get("is_admin", 0))
                })
            except Exception as e:
                self.send_json(400, {"detail": f"Registration failed: {str(e)}"})
            return

        # 3. Create App with Chosen Models
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
                allowed_models = body.get("allowed_models") or [
                    "gemini-3.8-flash-low",
                    "gemini-3.8-flash-medium",
                    "gemini-3.8-flash-high",
                    "gemini-2.5-flash",
                    "gemini-2.5-pro"
                ]
                new_app = db.create_app(
                    user_id=user["id"],
                    name=name,
                    rate_limit_rpm=int(body.get("rate_limit_rpm", 15)),
                    daily_token_limit=int(body.get("daily_token_limit", 500000)),
                    allowed_models=allowed_models,
                    access_type=body.get("access_type", "sandboxed_tools"),
                    max_effort=body.get("max_effort", "medium"),
                    custom_api_key=body.get("api_key")
                )
                self.send_json(200, new_app)
            except Exception as e:
                self.send_json(400, {"detail": str(e)})
            return

        # 4. Token Guard Update
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

        # 6. OpenAI-Compatible Chat Completions
        if path == "/v1/chat/completions":
            caller = self.authenticate_caller()
            if not caller:
                self.send_json(401, {"detail": "Unauthorized API Key"})
                return
            app_info = caller["app"]

            allowed, _ = db.check_rate_limit(app_info["id"], app_info["rate_limit_rpm"])
            if not allowed:
                self.send_json(429, {"detail": f"Rate limit exceeded: {app_info['rate_limit_rpm']} RPM"})
                return

            req_model = body.get("model") or "gemini-3.8-flash-low"
            if not is_model_allowed(req_model, app_info["allowed_models"]):
                self.send_json(403, {"detail": f"Model '{req_model}' not allowed for this App"})
                return

            messages = body.get("messages", [])
            last_prompt = ""
            for m in reversed(messages):
                if m.get("role", "").lower() == "user":
                    last_prompt = m.get("content", "")
                    break

            if not last_prompt:
                self.send_json(400, {"detail": "No user message provided"})
                return

            target_model = normalize_model(req_model)
            ephemeral = body.get("ephemeral", False)
            requested_cid = body.get("conversation_id")

            # Resolve conversation session (prevents chat explosion)
            cid, should_cleanup = conversation_manager.get_or_create_conversation(
                app_id=app_info["id"],
                requested_cid=requested_cid,
                ephemeral=ephemeral
            )

            cmd = [
                AGY_PATH,
                "-p", last_prompt,
                "--output-format", "json",
                "--sandbox",
                "--conversation", cid
            ]
            if target_model:
                cmd.extend(["--model", target_model])

            try:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
                content = proc.stdout.strip()
                try:
                    parsed_out = json.loads(content)
                    if isinstance(parsed_out, dict) and "response" in parsed_out:
                        content = parsed_out["response"]
                except Exception:
                    pass

                self.send_json(200, {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": req_model,
                    "conversation_id": cid,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop"
                    }]
                })
            except Exception as e:
                self.send_json(500, {"detail": f"Agent execution error: {str(e)}"})
            finally:
                if should_cleanup:
                    conversation_manager.cleanup_conversation(cid)
            return

        # 7. Streaming Chat (/v1/chat/stream)
        if path == "/v1/chat/stream":
            caller = self.authenticate_caller()
            if not caller:
                self.send_json(401, {"detail": "Unauthorized API Key"})
                return
            app_info = caller["app"]

            allowed, _ = db.check_rate_limit(app_info["id"], app_info["rate_limit_rpm"])
            if not allowed:
                self.send_json(429, {"detail": f"Rate limit exceeded: {app_info['rate_limit_rpm']} RPM"})
                return

            message = body.get("message", "").strip()
            if not message:
                self.send_json(400, {"detail": "Message required"})
                return

            req_model = body.get("model") or "gemini-3.8-flash-low"
            if not is_model_allowed(req_model, app_info["allowed_models"]):
                self.send_json(403, {"detail": f"Model '{req_model}' not allowed"})
                return

            effective_effort = body.get("effort") or app_info.get("max_effort", "medium")
            target_model = normalize_model(req_model)
            ephemeral = body.get("ephemeral", False)
            requested_cid = body.get("conversation_id")

            # Resolve conversation session (prevents chat explosion)
            cid, should_cleanup = conversation_manager.get_or_create_conversation(
                app_id=app_info["id"],
                requested_cid=requested_cid,
                ephemeral=ephemeral
            )

            # SSE Header
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_cors_headers()
            self.end_headers()

            # Execute agy subprocess stream with conversation id
            cmd = [
                AGY_PATH,
                "-p", message,
                "--output-format", "stream-json",
                "--sandbox",
                "--conversation", cid
            ]
            if target_model:
                cmd.extend(["--model", target_model])
            if effective_effort and not any(k in target_model.lower() for k in ["-low", "-medium", "-high"]):
                cmd.extend(["--effort", effective_effort])

            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
                for line in proc.stdout:
                    line_str = line.strip()
                    if line_str:
                        self.wfile.write(f"data: {line_str}\n\n".encode("utf-8"))
                        self.wfile.flush()
                proc.wait()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except Exception as e:
                err_data = json.dumps({"error": str(e)})
                self.wfile.write(f"data: {err_data}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            finally:
                if should_cleanup:
                    conversation_manager.cleanup_conversation(cid)
            return

        self.send_json(404, {"detail": "Route not found"})

    # ---------------------------------------------------------------
    # PUT & DELETE Requests
    # ---------------------------------------------------------------
    def do_PUT(self):
        parsed = urlparse(self.path)
        match_app = re.match(r"^/v1/apps/([^/]+)$", parsed.path)
        if match_app:
            user = self.authenticate_user()
            if not user:
                self.send_json(401, {"detail": "Unauthorized"})
                return
            app_id = match_app.group(1)
            body = self.read_json_body()
            success = db.update_app_settings(app_id, user["id"], body)
            if not success:
                self.send_json(404, {"detail": "App not found or permission denied"})
                return
            self.send_json(200, {"status": "success", "message": "App updated successfully"})
            return
        self.send_json(404, {"detail": "Route not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        match_app = re.match(r"^/v1/apps/([^/]+)$", parsed.path)
        if match_app:
            user = self.authenticate_user()
            if not user:
                self.send_json(401, {"detail": "Unauthorized"})
                return
            app_id = match_app.group(1)
            success = db.delete_app(app_id, user["id"])
            if not success:
                self.send_json(404, {"detail": "App not found or permission denied"})
                return
            self.send_json(200, {"status": "success", "message": "App deleted successfully"})
            return
        self.send_json(404, {"detail": "Route not found"})

# -------------------------------------------------------------------
# Server Runner with Mobile Connection-Reset Protection
# -------------------------------------------------------------------
class SilentThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc_type, _, _ = sys.exc_info()
        if exc_type in (BrokenPipeError, ConnectionResetError):
            return  # Suppress normal client disconnection noise
        super().handle_error(request, client_address)

def run_standalone_server(port: int = 8000, host: str = "0.0.0.0"):
    db.init_db()
    # Trigger background cleanup of stale sessions older than 24h
    threading.Thread(target=conversation_manager.purge_expired_sessions, daemon=True).start()

    server_address = (host, port)
    httpd = SilentThreadingHTTPServer(server_address, AntigravityHandler)
    logger.info(f"Antigravity Zero-Dependency Server running on http://{host}:{port}")
    logger.info(f"Session TTL: {conversation_manager.ttl // 60} minutes | Compatible with Python 3.8 to 3.14+")
    logger.info("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("\nShutting down server gracefully...")
        httpd.shutdown()

if __name__ == "__main__":
    p = int(os.environ.get("PORT", "8000"))
    h = os.environ.get("HOST", "0.0.0.0")
    run_standalone_server(port=p, host=h)
