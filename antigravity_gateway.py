"""
Secure Multi-Tenant Antigravity API Gateway Server
=================================================
Enterprise-grade gateway featuring:
- User login & self-service account management (personal workspace, personal keys).
- Multi-App management (isolated API keys per app, sliding-window rate limits, allowed models).
- Token Drain Guard (automatic threshold checks, large prompt interception, reasoning effort caps).
- Interactive approval engine with real-time async release.
- OpenAI-compatible and SSE streaming endpoints.
- Mobile-optimized management console & Android Termux integration.
"""

import os
import sys
import json
import uuid
import asyncio
import shutil
import logging
import re
import urllib.request
from urllib.parse import quote
from typing import AsyncGenerator, Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, status, Header, Request
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import db
from web_ui import WEB_UI_HTML

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("antigravity_gateway")

GATEWAY_DIR = Path(__file__).resolve().parent

# Locate agy executable
AGY_PATH = shutil.which("agy")
if not AGY_PATH:
    default_win_path = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
    if default_win_path.exists():
        AGY_PATH = str(default_win_path)
    else:
        AGY_PATH = "agy.exe"

DEFAULT_SANDBOX_DIR = GATEWAY_DIR / "sandbox_workspace"
DEFAULT_SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

# -------------------------------------------------------------------
# FastAPI App Initialization
# -------------------------------------------------------------------
app = FastAPI(
    title="Antigravity Enterprise Gateway",
    description="Multi-tenant API Gateway with App Rate Limiting and Token Drain Protection",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# In-Memory Async Approval Notifier
# -------------------------------------------------------------------
class LiveApprovalTracker:
    def __init__(self):
        self.events: Dict[str, asyncio.Event] = {}
        self.decisions: Dict[str, str] = {}
        self.notes: Dict[str, Optional[str]] = {}

    def register(self, approval_id: str) -> asyncio.Event:
        event = asyncio.Event()
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
# Authentication Dependencies
# -------------------------------------------------------------------
async def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Authenticates a user via Bearer User Token (usr_...)"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    token = parts[1]
    user = db.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=403, detail="Invalid or expired user session token")
    return user

async def get_caller_identity(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """
    Authenticates requests coming to the AI endpoints (/v1/chat/*).
    Accepts EITHER:
    1. An App API Key (agy_app_...) -> Resolves App + Owner User.
    2. A User Token (usr_...) -> Resolves User + Uses User's default App.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header. Provide Bearer <APP_KEY> or <USER_TOKEN>")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format. Expected 'Bearer <TOKEN>'")

    token = parts[1]

    # Check App API Key first
    app_info = db.get_app_by_key(token)
    if app_info:
        if app_info["status"] != "active":
            raise HTTPException(status_code=403, detail="This application has been suspended")
        user = db.get_user_by_token(app_info["user_id"]) or {"id": app_info["user_id"]}
        return {"type": "app", "app": app_info, "user": user}

    # Check User Token
    user = db.get_user_by_token(token)
    if user:
        apps = db.list_user_apps(user["id"])
        default_app = apps[0] if apps else None
        if not default_app:
            default_app = db.create_app(user["id"], "Default Console App")
        return {"type": "user", "app": default_app, "user": user}

    raise HTTPException(status_code=403, detail="Invalid API Key or Session Token")

# -------------------------------------------------------------------
# Request Models
# -------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    personal_api_key: Optional[str] = None
    custom_workspace: Optional[str] = None

class CreateAppRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    rate_limit_rpm: int = Field(15, ge=1, le=120)
    daily_token_limit: int = Field(500000, ge=1000)
    allowed_models: List[str] = Field(["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.8-flash-low", "gemini-3.8-flash-medium", "gemini-3.8-flash-high"])
    access_type: str = Field("sandboxed_tools")
    max_effort: str = Field("medium")
    api_key: Optional[str] = None

class UpdateAppRequest(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    rate_limit_rpm: Optional[int] = None
    daily_token_limit: Optional[int] = None
    allowed_models: Optional[List[str]] = None
    access_type: Optional[str] = None
    max_effort: Optional[str] = None
    api_key: Optional[str] = None

class UpdateProfileRequest(BaseModel):
    personal_api_key: Optional[str] = None
    custom_workspace: Optional[str] = None

class UpdateTokenGuardRequest(BaseModel):
    max_prompt_chars: int = Field(..., ge=500, le=200000)
    max_reasoning_effort: str = Field(...)
    expensive_model_policy: str = Field(...)
    block_high_effort: int = Field(0)
    daily_system_token_cap: int = Field(..., ge=10000)

class ChatStreamRequest(BaseModel):
    message: str = Field(..., description="Prompt or instruction")
    conversation_id: Optional[str] = None
    ephemeral: Optional[bool] = False
    model: Optional[str] = "gemini-3.8-flash-low"
    effort: Optional[str] = None
    sandbox: Optional[bool] = None
    require_approval: Optional[bool] = False

class ApprovalDecisionRequest(BaseModel):
    decision: str
    notes: Optional[str] = None

class MessageItem(BaseModel):
    role: str
    content: str

class OpenAIChatRequest(BaseModel):
    model: Optional[str] = "gemini-3.8-flash-low"
    messages: List[MessageItem]
    conversation_id: Optional[str] = None
    ephemeral: Optional[bool] = False
    stream: Optional[bool] = False
    effort: Optional[str] = "medium"

# -------------------------------------------------------------------
# Token Drain & Safety Guard
# -------------------------------------------------------------------
EFFORT_RANKS = {"low": 1, "medium": 2, "high": 3, "xhigh": 4, "max": 5}

def evaluate_token_drain_risk(
    prompt: str,
    requested_model: str,
    requested_effort: str,
    app_info: Dict[str, Any],
    policy: Dict[str, Any]
) -> Tuple[bool, Optional[str]]:
    """
    Evaluates whether the request poses a significant token drain risk.
    Returns: (requires_approval, risk_reason)
    """
    # 1. Prompt Length Check
    prompt_len = len(prompt)
    max_chars = policy.get("max_prompt_chars", 10000)
    if prompt_len > max_chars:
        return True, f"Token Drain Alert: Prompt size ({prompt_len:,} chars) exceeds safety threshold ({max_chars:,} chars)"

    # 2. Reasoning Effort Check
    req_rank = EFFORT_RANKS.get(requested_effort.lower(), 2)
    max_allowed_rank = EFFORT_RANKS.get(app_info.get("max_effort", "medium").lower(), 2)
    policy_max_rank = EFFORT_RANKS.get(policy.get("max_reasoning_effort", "medium").lower(), 2)

    if req_rank > max_allowed_rank:
        return True, f"Token Drain Alert: Requested effort '{requested_effort}' exceeds App limit '{app_info.get('max_effort')}'"

    if req_rank > policy_max_rank:
        return True, f"Token Drain Alert: Effort '{requested_effort}' exceeds System Token Safety threshold '{policy.get('max_reasoning_effort')}'"

    if policy.get("block_high_effort") and req_rank >= 3:
        return True, "Token Drain Alert: High reasoning effort is flagged for manual review by system administrator"

    # 3. Expensive Model Check
    if "pro" in requested_model.lower() or "ultra" in requested_model.lower():
        if policy.get("expensive_model_policy") == "require_approval":
            return True, f"Token Drain Alert: Premium model '{requested_model}' requires approval before consumption"

    # 4. App Daily Token Limit Check
    if app_info.get("total_tokens_used", 0) >= app_info.get("daily_token_limit", 500000):
        return True, f"Token Drain Alert: App '{app_info['name']}' has exhausted its daily token quota ({app_info['daily_token_limit']:,} tokens)"

    return False, None

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
    """Maps legacy or shorthand model names to supported agy models."""
    if not model_name:
        return "gemini-3.8-flash-low"
    m = model_name.strip().lower()
    return MODEL_ALIASES.get(m, model_name.strip())

def is_model_allowed(requested_model: str, allowed_models: List[str]) -> bool:
    """Checks whether requested model or its normalized canonical form is in allowed_models."""
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
BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"
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
        self.lock = asyncio.Lock()

    async def get_or_create_conversation(
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
        async with self.lock:
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
# Antigravity Subprocess Execution
# -------------------------------------------------------------------
async def execute_agent(
    prompt: str,
    conversation_id: Optional[str] = None,
    sandbox: bool = True,
    effort: str = "medium",
    workspace_path: Optional[str] = None,
    app_id: Optional[str] = None,
    model: Optional[str] = None
) -> AsyncGenerator[str, None]:
    cwd = workspace_path or str(DEFAULT_SANDBOX_DIR)
    Path(cwd).mkdir(parents=True, exist_ok=True)

    target_model = normalize_model(model)
    cmd = [
        AGY_PATH,
        "-p", prompt,
        "--output-format", "stream-json"
    ]
    if target_model:
        cmd.extend(["--model", target_model])
    # agy only accepts --effort when not pre-baked into the model identifier
    if effort and not any(k in target_model.lower() for k in ["-low", "-medium", "-high"]):
        cmd.extend(["--effort", effort])
    if sandbox:
        cmd.append("--sandbox")
    if conversation_id:
        cmd.extend(["--conversation", conversation_id])

    logger.info(f"Launching agy subprocess [Model: {target_model}, Effort: {effort}, Sandbox: {sandbox}] in {cwd}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    except Exception as e:
        yield f"data: {json.dumps({'error': f'Failed to spawn Antigravity binary: {str(e)}'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    tokens_recorded = False
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            line_str = line.decode("utf-8", errors="replace").strip()
            if line_str:
                yield f"data: {line_str}\n\n"

                # Check if final usage is reported
                if not tokens_recorded and app_id and '"usage"' in line_str:
                    try:
                        parsed = json.loads(line_str)
                        if "usage" in parsed and "total_tokens" in parsed["usage"]:
                            db.log_token_usage(app_id, parsed["usage"]["total_tokens"])
                            tokens_recorded = True
                    except Exception:
                        pass

        await proc.wait()
    except asyncio.CancelledError:
        proc.terminate()
        raise
    finally:
        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        # Estimate fallback tokens if not reported
        if not tokens_recorded and app_id:
            estimated = max(50, len(prompt) // 4)
            db.log_token_usage(app_id, estimated)

        yield "data: [DONE]\n\n"

# -------------------------------------------------------------------
# Static & Web UI Routes
# -------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
async def serve_web_ui():
    return HTMLResponse(content=WEB_UI_HTML)

@app.get("/client.sh", response_class=PlainTextResponse)
async def serve_client_script(request: Request):
    client_sh_path = GATEWAY_DIR / "client.sh"
    if client_sh_path.exists():
        content = client_sh_path.read_text(encoding="utf-8")
        base_url = str(request.base_url).rstrip("/")
        content = content.replace('DEFAULT_SERVER="https://royal-crossing-boxing-inform.trycloudflare.com"', f'DEFAULT_SERVER="{base_url}"')
        return PlainTextResponse(content=content, media_type="text/x-sh")
    raise HTTPException(status_code=404, detail="client.sh not found")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "antigravity-enterprise-gateway",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "token_guard": db.get_token_guard_policy()
    }

SUPPORTED_MODELS = [
    {"id": "gemini-3.8-flash-high", "name": "Gemini 3.8 Flash (High Effort)"},
    {"id": "gemini-3.8-flash-medium", "name": "Gemini 3.8 Flash (Medium Effort)"},
    {"id": "gemini-3.8-flash-low", "name": "Gemini 3.8 Flash (Low Effort)"},
    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash (Fast & Efficient)"},
    {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro (Deep Reasoning)"},
    {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6 (Thinking)"},
    {"id": "claude-opus-4-6-thinking", "name": "Claude Opus 4.6 (Thinking)"},
    {"id": "gpt-oss-120b-medium", "name": "GPT-OSS 120B (Medium)"},
]

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": m["id"],
                "object": "model",
                "name": m["name"],
                "created": 1700000000,
                "owned_by": "antigravity"
            }
            for m in SUPPORTED_MODELS
        ]
    }

# -------------------------------------------------------------------
# User Auth Endpoints
# -------------------------------------------------------------------
@app.post("/v1/auth/login")
async def login(req: LoginRequest):
    user = db.authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password. Default is admin / admin")
    token_val = user.get("user_token") or user.get("token")
    return {
        "status": "success",
        "user_id": user["id"],
        "username": user["username"],
        "token": token_val,
        "user_token": token_val,
        "user": {"token": token_val, "username": user["username"]},
        "is_admin": user["is_admin"]
    }

@app.post("/v1/auth/register")
async def register(req: RegisterRequest):
    try:
        res = db.create_user(req.username, req.password, req.personal_api_key, req.custom_workspace)
        return {"status": "success", "user": res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/v1/auth/me")
async def get_profile(user: Dict[str, Any] = Depends(get_current_user)):
    apps = db.list_user_apps(user["id"])
    return {
        "id": user["id"],
        "username": user["username"],
        "is_admin": bool(user["is_admin"]),
        "personal_api_key": user.get("personal_api_key"),
        "custom_workspace": user.get("custom_workspace"),
        "apps_count": len(apps)
    }

# -------------------------------------------------------------------
# Multi-App Management Endpoints
# -------------------------------------------------------------------
@app.get("/v1/apps")
async def list_apps(user: Dict[str, Any] = Depends(get_current_user)):
    return db.list_user_apps(user["id"])

@app.post("/v1/apps")
async def create_new_app(req: CreateAppRequest, user: Dict[str, Any] = Depends(get_current_user)):
    try:
        new_app = db.create_app(
            user_id=user["id"],
            name=req.name,
            rate_limit_rpm=req.rate_limit_rpm,
            daily_token_limit=req.daily_token_limit,
            allowed_models=req.allowed_models,
            access_type=req.access_type,
            max_effort=req.max_effort,
            custom_api_key=req.api_key
        )
        return {"status": "success", "app": new_app}
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            raise HTTPException(status_code=400, detail="An App with this API key already exists. Please choose a unique key.")
        raise HTTPException(status_code=400, detail=f"Failed to create app: {str(e)}")

@app.put("/v1/apps/{app_id}")
async def update_app(app_id: str, req: UpdateAppRequest, user: Dict[str, Any] = Depends(get_current_user)):
    raw_data = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    updates = {k: v for k, v in raw_data.items() if v is not None}
    success = db.update_app_settings(app_id, user["id"], updates)
    if not success:
        raise HTTPException(status_code=404, detail="App not found or permission denied")
    return {"status": "success", "message": "App updated successfully"}

@app.delete("/v1/apps/{app_id}")
async def delete_app(app_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    success = db.delete_app(app_id, user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="App not found or permission denied")
    return {"status": "success", "message": "App deleted successfully"}

# -------------------------------------------------------------------
# Token Guard Policy Endpoints
# -------------------------------------------------------------------
@app.get("/v1/token-guard")
async def get_token_guard(user: Dict[str, Any] = Depends(get_current_user)):
    return db.get_token_guard_policy()

@app.post("/v1/token-guard")
async def update_token_guard(req: UpdateTokenGuardRequest, user: Dict[str, Any] = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Only administrators can adjust global token guard policies")
    policy_data = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    db.update_token_guard_policy(policy_data)
    return {"status": "success", "policy": db.get_token_guard_policy()}

# -------------------------------------------------------------------
# Approval Workflows
# -------------------------------------------------------------------
@app.get("/v1/approvals/pending")
async def get_pending_approvals(user: Dict[str, Any] = Depends(get_current_user)):
    return db.list_pending_approvals(user["id"])

@app.post("/v1/approvals/{approval_id}/respond")
async def respond_approval(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    user: Dict[str, Any] = Depends(get_current_user)
):
    decision = payload.decision.lower().strip()
    if decision not in ("approve", "deny"):
        raise HTTPException(status_code=400, detail="Decision must be 'approve' or 'deny'")

    success = db.resolve_approval(approval_id, decision, payload.notes)
    if not success:
        raise HTTPException(status_code=404, detail="Approval ticket not found or already resolved")

    # Wake up waiting stream turn
    approval_tracker.resolve(approval_id, decision, payload.notes)
    logger.info(f"User {user['username']} resolved approval ticket {approval_id}: {decision}")
    return {"status": "success", "approval_id": approval_id, "decision": decision}

# -------------------------------------------------------------------
# AI Chat Endpoints (Protected by App Rate Limit & Token Drain Guard)
# -------------------------------------------------------------------
@app.post("/v1/chat/stream")
async def chat_stream(
    req: ChatStreamRequest,
    request: Request,
    caller: Dict[str, Any] = Depends(get_caller_identity)
):
    app_info = caller["app"]
    user_info = caller["user"]
    client_ip = request.client.host if request.client else "unknown"

    # 1. Rate Limit Check (Sliding Window per App)
    allowed, count = db.check_rate_limit(app_info["id"], app_info["rate_limit_rpm"])
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for app '{app_info['name']}'. Limit: {app_info['rate_limit_rpm']} requests/minute."
        )

    # 2. Allowed Models Check
    req_model = req.model or "gemini-2.5-flash"
    if not is_model_allowed(req_model, app_info["allowed_models"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Model '{req_model}' is not permitted for app '{app_info['name']}'. Allowed models: {app_info['allowed_models']}"
        )

    # 3. Access Type Restriction
    effective_sandbox = True if app_info["access_type"] == "sandboxed_tools" else req.sandbox
    if app_info["access_type"] == "chat_only":
        effective_sandbox = True

    # 4. Effort Negotiation
    effective_effort = req.effort or app_info.get("max_effort", "medium")

    # 5. Token Drain Risk Assessment
    policy = db.get_token_guard_policy()
    drain_risk, drain_reason = evaluate_token_drain_risk(
        prompt=req.message,
        requested_model=req_model,
        requested_effort=effective_effort,
        app_info=app_info,
        policy=policy
    )

    needs_approval = req.require_approval or drain_risk

    async def stream_generator():
        # Handle Approval Workflow if triggered
        if needs_approval:
            reason_text = drain_reason or "User-requested approval prior to execution"
            approval_id = db.create_approval(
                app_id=app_info["id"],
                user_id=user_info["id"],
                prompt=req.message,
                reason=reason_text,
                details=f"Model: {req_model} | Effort: {effective_effort} | App: {app_info['name']}",
                client_ip=client_ip
            )
            event = approval_tracker.register(approval_id)

            yield f"data: {json.dumps({'event': 'approval_required', 'approval_id': approval_id, 'reason': reason_text})}\n\n"

            # Wait for decision (timeout 180s)
            try:
                await asyncio.wait_for(event.wait(), timeout=180.0)
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'event': 'approval_timeout', 'error': 'Approval ticket timed out after 180 seconds.'})}\n\n"
                yield "data: [DONE]\n\n"
                approval_tracker.cleanup(approval_id)
                return

            decision = approval_tracker.get_decision(approval_id)
            if decision != "approve":
                yield f"data: {json.dumps({'event': 'approval_rejected', 'message': 'Execution denied by administrator.'})}\n\n"
                yield "data: [DONE]\n\n"
                approval_tracker.cleanup(approval_id)
                return

            yield f"data: {json.dumps({'event': 'approval_granted', 'message': 'Approval confirmed. Executing agent...'})}\n\n"
            approval_tracker.cleanup(approval_id)

        # Determine workspace
        user_workspace = user_info.get("custom_workspace") or str(DEFAULT_SANDBOX_DIR)

        # Resolve conversation session (prevents chat explosion)
        cid, should_cleanup = await conversation_manager.get_or_create_conversation(
            app_id=app_info["id"],
            requested_cid=req.conversation_id,
            ephemeral=bool(req.ephemeral)
        )

        try:
            # Execute Antigravity agent
            async for chunk in execute_agent(
                prompt=req.message,
                conversation_id=cid,
                sandbox=effective_sandbox,
                effort=effective_effort,
                workspace_path=user_workspace,
                app_id=app_info["id"],
                model=req_model
            ):
                yield chunk
        finally:
            if should_cleanup:
                conversation_manager.cleanup_conversation(cid)

    return StreamingResponse(stream_generator(), media_type="text/event-stream")

@app.post("/v1/chat/completions")
async def openai_completions(
    req: OpenAIChatRequest,
    caller: Dict[str, Any] = Depends(get_caller_identity)
):
    app_info = caller["app"]
    user_info = caller["user"]

    # Rate Limit
    allowed, count = db.check_rate_limit(app_info["id"], app_info["rate_limit_rpm"])
    if not allowed:
        raise HTTPException(status_code=429, detail=f"Rate limit exceeded: {app_info['rate_limit_rpm']} RPM")

    # Allowed Model
    req_model = req.model or "gemini-2.5-flash"
    if not is_model_allowed(req_model, app_info["allowed_models"]):
        raise HTTPException(status_code=403, detail=f"Model '{req_model}' not allowed for this App")

    # Extract user prompt
    last_prompt = ""
    for msg in reversed(req.messages):
        if msg.role.lower() == "user":
            last_prompt = msg.content
            break

    if not last_prompt:
        raise HTTPException(status_code=400, detail="No user message provided")

    # Token Drain Check
    policy = db.get_token_guard_policy()
    drain_risk, drain_reason = evaluate_token_drain_risk(
        prompt=last_prompt,
        requested_model=req_model,
        requested_effort=req.effort or "medium",
        app_info=app_info,
        policy=policy
    )

    if drain_risk:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Blocked by Token Drain Guard: {drain_reason}. High-token operations require approval via streaming API."
        )

    user_workspace = user_info.get("custom_workspace") or str(DEFAULT_SANDBOX_DIR)

    # Resolve conversation session (prevents chat explosion)
    cid, should_cleanup = await conversation_manager.get_or_create_conversation(
        app_id=app_info["id"],
        requested_cid=req.conversation_id,
        ephemeral=bool(req.ephemeral)
    )

    if req.stream:
        async def stream_wrapper():
            try:
                async for chunk in execute_agent(
                    prompt=last_prompt,
                    conversation_id=cid,
                    sandbox=True,
                    effort=req.effort or "medium",
                    workspace_path=user_workspace,
                    app_id=app_info["id"],
                    model=req_model
                ):
                    yield chunk
            finally:
                if should_cleanup:
                    conversation_manager.cleanup_conversation(cid)
        return StreamingResponse(stream_wrapper(), media_type="text/event-stream")

    # Non-streamed
    target_model = normalize_model(req_model)
    cmd = [
        AGY_PATH,
        "-p", last_prompt,
        "--output-format", "json",
        "--sandbox",
        "--conversation", cid
    ]
    if target_model:
        cmd.extend(["--model", target_model])
    if req.effort and not any(k in target_model.lower() for k in ["-low", "-medium", "-high"]):
        cmd.extend(["--effort", req.effort])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=user_workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        output_text = stdout.decode("utf-8", errors="replace").strip()
        try:
            parsed_out = json.loads(output_text)
            if isinstance(parsed_out, dict) and "response" in parsed_out:
                output_text = parsed_out["response"]
        except Exception:
            pass

        # Log tokens
        estimated = max(50, (len(last_prompt) + len(output_text)) // 4)
        db.log_token_usage(app_info["id"], estimated)

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(datetime.now(timezone.utc).timestamp()),
            "model": req_model,
            "conversation_id": cid,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": output_text
                },
                "finish_reason": "stop"
            }]
        }
    finally:
        if should_cleanup:
            conversation_manager.cleanup_conversation(cid)

if __name__ == "__main__":
    import uvicorn
    # Trigger background cleanup of stale sessions older than 24h
    threading.Thread(target=conversation_manager.purge_expired_sessions, daemon=True).start()
    uvicorn.run("antigravity_gateway:app", host="127.0.0.1", port=8000, reload=False)
