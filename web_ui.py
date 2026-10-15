"""
Multi-Tenant Web UI for Antigravity Gateway
===========================================
Includes:
- User login, registration, and session management.
- Multi-App dashboard (create/edit/delete apps, configure rate limits, model access, and effort caps).
- Token Drain Guard & Approvals dashboard.
- Interactive Chat canvas with App-identity selector.
- App-scoped How to Connect guides (Termux, OpenWebUI, cURL, Python).
"""

WEB_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Antigravity Enterprise Gateway</title>
  <style>
    :root {
      --bg-primary: #0a0e17;
      --bg-secondary: #111827;
      --bg-card: #1a2234;
      --bg-card-hover: #222d44;
      --border: #2d3748;
      --text-main: #f9fafb;
      --text-muted: #94a3b8;
      --accent: #6366f1;
      --accent-hover: #4f46e5;
      --success: #10b981;
      --danger: #ef4444;
      --warning: #f59e0b;
      --radius: 10px;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    body { background-color: var(--bg-primary); color: var(--text-main); display: flex; flex-direction: column; min-height: 100vh; }

    /* Header */
    header {
      background-color: var(--bg-secondary);
      border-bottom: 1px solid var(--border);
      padding: 12px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 50;
    }
    .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 1.15rem; }
    .user-pill {
      display: flex;
      align-items: center;
      gap: 10px;
      background: var(--bg-card);
      padding: 4px 12px;
      border-radius: 9999px;
      border: 1px solid var(--border);
      font-size: 0.85rem;
    }

    /* Nav Tabs */
    nav {
      display: flex;
      background-color: var(--bg-secondary);
      border-bottom: 1px solid var(--border);
      overflow-x: auto;
      padding: 0 16px;
    }
    .nav-btn {
      padding: 14px 18px;
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 0.92rem;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      border-bottom: 2px solid transparent;
      white-space: nowrap;
    }
    .nav-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
    .badge { background: var(--danger); color: white; border-radius: 10px; padding: 2px 7px; font-size: 0.72rem; }

    main { flex: 1; max-width: 1000px; width: 100%; margin: 0 auto; padding: 20px 16px; display: flex; flex-direction: column; }
    .tab-content { display: none; flex-direction: column; flex: 1; }
    .tab-content.active { display: flex; }

    /* Cards & Containers */
    .card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px;
      margin-bottom: 18px;
    }
    .card h3 { margin-bottom: 12px; font-size: 1.1rem; display: flex; align-items: center; justify-content: space-between; }

    .form-group { margin-bottom: 14px; }
    .form-group label { display: block; font-size: 0.82rem; color: var(--text-muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
    input[type="text"], input[type="password"], input[type="number"], select, textarea {
      width: 100%;
      padding: 10px 14px;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: var(--bg-secondary);
      color: white;
      font-size: 0.95rem;
    }
    input:focus, select:focus, textarea:focus { outline: 1px solid var(--accent); }

    .btn-primary {
      padding: 10px 18px;
      background-color: var(--accent);
      color: white;
      border: none;
      border-radius: 6px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .btn-primary:hover { background-color: var(--accent-hover); }
    .btn-secondary {
      padding: 8px 14px;
      background: var(--border);
      color: var(--text-main);
      border: 1px solid var(--border);
      border-radius: 6px;
      cursor: pointer;
      font-weight: 500;
    }
    .btn-danger {
      padding: 6px 12px;
      background: rgba(239, 68, 68, 0.15);
      color: var(--danger);
      border: 1px solid var(--danger);
      border-radius: 6px;
      cursor: pointer;
    }

    /* App Cards Grid */
    .app-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; margin-top: 14px; }
    .app-card {
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .app-card-header { display: flex; justify-content: space-between; align-items: flex-start; }
    .app-title { font-weight: 700; font-size: 1.05rem; color: white; }
    .app-tags { display: flex; flex-wrap: wrap; gap: 6px; font-size: 0.75rem; }
    .tag { background: rgba(99, 102, 241, 0.15); color: #818cf8; padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(99, 102, 241, 0.3); }
    .tag-rpm { background: rgba(16, 185, 129, 0.15); color: var(--success); border-color: rgba(16, 185, 129, 0.3); }
    .tag-danger { background: rgba(239, 68, 68, 0.15); color: var(--danger); border-color: rgba(239, 68, 68, 0.3); }

    .key-box {
      background: var(--bg-primary);
      border: 1px solid var(--border);
      padding: 8px 10px;
      border-radius: 6px;
      font-family: monospace;
      font-size: 0.8rem;
      color: #38bdf8;
      display: flex;
      justify-content: space-between;
      align-items: center;
      word-break: break-all;
    }

    /* Progress bar */
    .progress-bar-bg { width: 100%; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; margin-top: 4px; }
    .progress-bar-fill { height: 100%; background: var(--accent); border-radius: 3px; }

    /* Modal */
    .modal-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.75);
      z-index: 100;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }
    .modal-backdrop.active { display: flex; }
    .modal {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      max-width: 500px;
      width: 100%;
      padding: 24px;
    }

    /* Chat Tab */
    #chat-messages {
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding-bottom: 16px;
      min-height: 380px;
      max-height: calc(100vh - 300px);
    }
    .msg { max-width: 85%; padding: 12px 16px; border-radius: var(--radius); line-height: 1.5; font-size: 0.95rem; word-break: break-word; }
    .msg.user { align-self: flex-end; background-color: var(--accent); color: white; border-bottom-right-radius: 2px; }
    .msg.agent { align-self: flex-start; background-color: var(--bg-card); border: 1px solid var(--border); color: var(--text-main); border-bottom-left-radius: 2px; white-space: pre-wrap; font-family: ui-monospace, monospace; }
    .msg.drain-alert { align-self: center; background: rgba(239, 68, 68, 0.15); color: #fca5a5; border: 1px solid var(--danger); font-size: 0.85rem; }

    /* Code blocks */
    pre.code-block {
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      padding: 12px;
      border-radius: 6px;
      overflow-x: auto;
      font-family: monospace;
      font-size: 0.85rem;
      margin: 10px 0;
      color: #38bdf8;
    }
    .code-container { position: relative; margin: 10px 0; }
    .copy-chip {
      position: absolute;
      top: 8px;
      right: 8px;
      background: var(--border);
      color: var(--text-muted);
      border: none;
      border-radius: 4px;
      padding: 3px 8px;
      font-size: 0.75rem;
      cursor: pointer;
    }
    .copy-chip:hover { color: white; background: var(--accent); }
  </style>
</head>
<body>

  <!-- Top Navigation Header -->
  <header>
    <div class="brand">
      <span>🛡️</span>
      <span>Antigravity Gateway</span>
    </div>
    <div style="display: flex; align-items: center; gap: 12px;">
      <div class="user-pill" id="user-display">
        <span style="color: var(--success);">●</span>
        <span id="user-name">Checking Session...</span>
      </div>
      <button class="btn-secondary" id="btn-auth-action" onclick="handleAuthAction()" style="padding: 4px 10px; font-size: 0.8rem;">Login</button>
    </div>
  </header>

  <!-- Surface Switcher Tabs -->
  <nav>
    <button class="nav-btn active" onclick="switchTab('apps')">📱 Apps & Rate Limits</button>
    <button class="nav-btn" onclick="switchTab('guard')">
      🛡️ Token Guard & Approvals <span class="badge" id="approvals-badge" style="display:none;">0</span>
    </button>
    <button class="nav-btn" onclick="switchTab('chat')">💬 Chat Console</button>
    <button class="nav-btn" onclick="switchTab('connect')">🔌 How to Connect</button>
  </nav>

  <main>
    <!-- TAB 1: Apps Management -->
    <div id="tab-apps" class="tab-content active">
      <div class="card">
        <h3>
          <span>Registered Applications</span>
          <button class="btn-primary" onclick="openCreateAppModal()">+ Create New App</button>
        </h3>
        <p style="font-size: 0.88rem; color: var(--text-muted); margin-bottom: 12px;">
          Each client (phone, bot, OpenWebUI, script) connects using its own isolated App API key with dedicated rate limits, token quotas, and model permissions.
        </p>

        <div class="app-grid" id="apps-container">
          <p style="color: var(--text-muted);">Loading applications...</p>
        </div>
      </div>
    </div>

    <!-- TAB 2: Token Drain Guard & Approvals -->
    <div id="tab-guard" class="tab-content">
      <div class="card" style="border-color: var(--danger);">
        <h3>⚠️ Token Drain Protection Engine</h3>
        <p style="font-size: 0.9rem; color: var(--text-muted); line-height: 1.5; margin-bottom: 14px;">
          Protects your Antigravity quotas from runaway prompts, recursive tool invocations, or excessive CoT reasoning tokens. Actions that exceed safety thresholds are automatically intercepted and require manual approval.
        </p>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
          <div class="form-group">
            <label>Max Prompt Size (Chars) Before Approval</label>
            <input type="number" id="guard-max-prompt" value="10000">
            <small style="color: var(--text-muted);">Prompts exceeding this size require admin approval.</small>
          </div>
          <div class="form-group">
            <label>Max Allowed Reasoning Effort Without Approval</label>
            <select id="guard-max-effort">
              <option value="low">Low only</option>
              <option value="medium" selected>Medium (Standard)</option>
              <option value="high">High</option>
            </select>
          </div>
        </div>

        <div style="margin-top: 10px;">
          <button class="btn-primary" onclick="saveTokenGuardPolicy()">Save Guardrail Settings</button>
        </div>
      </div>

      <div class="card">
        <h3>
          <span>Pending Execution Approvals</span>
          <button class="btn-secondary" onclick="fetchPendingApprovals()">🔄 Refresh</button>
        </h3>
        <div id="approvals-list">
          <p style="color: var(--text-muted); font-size: 0.9rem;">No actions currently waiting for approval.</p>
        </div>
      </div>
    </div>

    <!-- TAB 3: Chat Console -->
    <div id="tab-chat" class="tab-content">
      <div style="display: flex; gap: 10px; margin-bottom: 12px; background: var(--bg-secondary); padding: 10px; border-radius: var(--radius); border: 1px solid var(--border); flex-wrap: wrap; align-items: center;">
        <label style="font-size: 0.85rem; color: var(--text-muted);">Chatting as App:</label>
        <select id="chat-app-selector" style="width: auto; padding: 4px 8px; font-size: 0.85rem;" onchange="updateChatModelOptions()">
          <option value="">Loading apps...</option>
        </select>
        <label style="font-size: 0.85rem; color: var(--text-muted); margin-left: 6px;">Model:</label>
        <select id="chat-model" style="width: auto; padding: 4px 8px; font-size: 0.85rem;">
          <option value="gemini-2.5-flash" selected>Gemini 2.5 Flash</option>
          <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
          <option value="gemini-3.8-flash-low">Gemini 3.8 Flash (Low)</option>
          <option value="gemini-3.8-flash-medium">Gemini 3.8 Flash (Med)</option>
          <option value="gemini-3.8-flash-high">Gemini 3.8 Flash (High)</option>
          <option value="claude-sonnet-4-6">Claude Sonnet 4.6</option>
          <option value="claude-opus-4-6-thinking">Claude Opus 4.6</option>
          <option value="gpt-oss-120b-medium">GPT-OSS 120B</option>
        </select>
        <label style="font-size: 0.85rem; color: var(--text-muted); margin-left: 6px;">Effort:</label>
        <select id="chat-effort" style="width: auto; padding: 4px 8px; font-size: 0.85rem;">
          <option value="low">Low</option>
          <option value="medium" selected>Medium</option>
          <option value="high">High (Guard Alert)</option>
        </select>
        <label style="font-size: 0.85rem; display: flex; align-items: center; gap: 4px; margin-left: 6px;">
          <input type="checkbox" id="chat-force-approval"> Force Approval
        </label>
        <button class="btn-secondary" style="margin-left: auto; padding: 4px 10px; font-size: 0.8rem;" onclick="clearChat()">Clear</button>
      </div>

      <div id="chat-messages">
        <div class="msg" style="align-self: center; background: rgba(99, 102, 241, 0.15); color: #818cf8; font-size: 0.85rem;">
          Select an application profile above and send a message. Token limits and drain guardrails apply.
        </div>
      </div>

      <div style="display: flex; gap: 8px; margin-top: 10px;">
        <textarea id="chat-prompt-input" rows="2" placeholder="Send a message to Antigravity..." onkeydown="handleChatKeyDown(event)"></textarea>
        <button class="btn-primary" onclick="sendChatMessage()" style="min-width: 80px; justify-content: center;">Send</button>
      </div>
    </div>

    <!-- TAB 4: How to Connect -->
    <div id="tab-connect" class="tab-content">
      <div class="card" style="border-color: var(--accent);">
        <h3>Select App to View Connection Guide</h3>
        <select id="connect-app-selector" onchange="renderAppConnectionGuide()" style="margin-bottom: 16px;">
          <option value="">Select an application...</option>
        </select>

        <div id="connect-guides">
          <!-- 1. Safe Keyless Virtual Middleware -->
          <div class="card" style="border-left: 4px solid var(--success);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <h4 style="color:var(--success);">🛡️ 1. Safe Keyless Virtual Middleware (Client Apps / Zero Keys)</h4>
              <span class="tag" style="background:rgba(16,185,129,0.2); color:var(--success);">Recommended for Frontend</span>
            </div>
            <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 8px;">
              Connect directly from your client apps (React, mobile APK, web app) with <strong>ZERO secret keys</strong>. CORS origin locking and rate limits protect your server automatically:
            </p>
            <div class="key-box" style="margin-bottom:12px;">
              <span id="vm-url-code" style="color:#38bdf8;">Loading endpoint...</span>
              <button class="btn-secondary" style="padding:2px 8px; font-size:0.75rem;" onclick="copySnippet('vm-url-code')">Copy URL</button>
            </div>
            <div style="margin-bottom:12px;">
              <div style="font-size:0.8rem; font-weight:600; color:#a5b4fc; margin-bottom:4px;">Python OpenAI SDK (Keyless):</div>
              <div class="code-container">
                <pre class="code-block" id="vm-py-code">Loading...</pre>
                <button class="copy-chip" onclick="copySnippet('vm-py-code')">Copy</button>
              </div>
            </div>
            <div>
              <div style="font-size:0.8rem; font-weight:600; color:#a5b4fc; margin-bottom:4px;">JavaScript / React OpenAI SDK (Keyless):</div>
              <div class="code-container">
                <pre class="code-block" id="vm-js-code">Loading...</pre>
                <button class="copy-chip" onclick="copySnippet('vm-js-code')">Copy</button>
              </div>
            </div>
          </div>

          <!-- 2. Direct Authenticated Backend API -->
          <div class="card">
            <h4>🔒 2. Backend Direct API (Standard Authenticated)</h4>
            <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 8px;">For server-to-server calls where the secret API key is safely kept in a backend <code>.env</code> file:</p>
            <table style="width:100%; border-collapse: collapse; font-size: 0.85rem; margin-bottom:10px;">
              <tr style="border-bottom: 1px solid var(--border);"><td style="padding:6px;">Base URL:</td><td style="padding:6px; font-family:monospace; color:#38bdf8;" id="openwebui-url">...</td></tr>
              <tr style="border-bottom: 1px solid var(--border);"><td style="padding:6px;">API Key:</td><td style="padding:6px; font-family:monospace; color:#38bdf8;" id="openwebui-key">...</td></tr>
              <tr><td style="padding:6px;">Model:</td><td style="padding:6px; font-family:monospace;">gemini-2.5-flash</td></tr>
            </table>
            <div class="code-container">
              <pre class="code-block" id="curl-app-code">Loading...</pre>
              <button class="copy-chip" onclick="copySnippet('curl-app-code')">Copy</button>
            </div>
          </div>

          <!-- 3. 1-Click Standalone Edge Middleware Snippets -->
          <div class="card">
            <h4>🚀 3. Standalone Edge Middleware (1-Click Next.js / Cloudflare Worker)</h4>
            <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 8px;">Ready-to-use edge proxy files to drop into your Next.js project or Cloudflare Worker:</p>
            <div style="margin-bottom:10px;">
              <div style="font-size:0.8rem; font-weight:600; color:#a5b4fc; margin-bottom:4px;">Next.js Edge Route (<code>app/api/chat/route.ts</code>):</div>
              <div class="code-container">
                <pre class="code-block" id="nextjs-route-code">Loading...</pre>
                <button class="copy-chip" onclick="copySnippet('nextjs-route-code')">Copy</button>
              </div>
            </div>
            <div>
              <div style="font-size:0.8rem; font-weight:600; color:#a5b4fc; margin-bottom:4px;">Cloudflare Worker (<code>worker.js</code>):</div>
              <div class="code-container">
                <pre class="code-block" id="cf-worker-code">Loading...</pre>
                <button class="copy-chip" onclick="copySnippet('cf-worker-code')">Copy</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </main>

  <!-- Login/Register Modal -->
  <div class="modal-backdrop" id="auth-modal">
    <div class="modal">
      <h3 id="auth-title" style="margin-bottom: 6px;">Login to Antigravity Gateway</h3>
      <p style="font-size: 0.82rem; color: var(--text-muted); margin-bottom: 16px;">
        Local Server Default: <strong style="color:var(--accent);">admin</strong> / <strong style="color:var(--accent);">admin</strong>
      </p>
      <div class="form-group">
        <label>Username</label>
        <input type="text" id="auth-username" value="admin" autocapitalize="none" autocorrect="off" spellcheck="false" placeholder="admin">
      </div>
      <div class="form-group">
        <label>Password</label>
        <input type="password" id="auth-password" value="admin" placeholder="admin">
      </div>
      <div style="display: flex; flex-direction: column; gap: 8px; margin-top: 18px;">
        <div style="display: flex; gap: 8px;">
          <button class="btn-primary" style="flex: 1;" onclick="submitAuth(true)">Login</button>
          <button class="btn-secondary" style="flex: 1; border-color: var(--accent); color: var(--accent);" onclick="quickAdminLogin()">⚡ 1-Click Admin</button>
        </div>
        <div style="display: flex; gap: 8px;">
          <button class="btn-secondary" style="flex: 1;" onclick="submitAuth(false)">Register New</button>
          <button class="btn-secondary" onclick="closeAuthModal()">Cancel</button>
        </div>
      </div>
      <div id="auth-error-msg" style="margin-top: 12px; color: #ef4444; font-size: 0.85rem; display: none;"></div>
    </div>
  </div>

  <!-- Create App Modal -->
  <div class="modal-backdrop" id="create-app-modal">
    <div class="modal">
      <h3 style="margin-bottom: 16px;">Create New Application</h3>
      <div class="form-group">
        <label>App Name</label>
        <input type="text" id="new-app-name" placeholder="e.g. Android Termux Client">
      </div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
        <div class="form-group">
          <label>Rate Limit (RPM)</label>
          <input type="number" id="new-app-rpm" value="15" min="1" max="120">
        </div>
        <div class="form-group">
          <label>Daily Token Cap</label>
          <input type="number" id="new-app-tokens" value="500000">
        </div>
      </div>
      <div class="form-group">
        <label>Max Reasoning Effort Allowed</label>
        <select id="new-app-effort">
          <option value="low">Low (Zero drain)</option>
          <option value="medium" selected>Medium (Standard)</option>
          <option value="high">High (Deep reasoning)</option>
        </select>
      </div>
      <div class="form-group">
        <label>Custom API Key (Optional - leave blank to auto-generate)</label>
        <input type="text" id="new-app-key" placeholder="e.g. my-custom-app-key-1234">
        <small style="color: var(--text-muted); font-size: 0.75rem;">You can specify your own manual key or leave empty to auto-generate.</small>
      </div>
      <div class="form-group">
        <label>Allowed Models</label>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 0.8rem; background: var(--bg-secondary); padding: 8px; border-radius: 6px; border: 1px solid var(--border); max-height: 120px; overflow-y: auto;">
          <label><input type="checkbox" name="app-model" value="gemini-2.5-flash" checked> gemini-2.5-flash</label>
          <label><input type="checkbox" name="app-model" value="gemini-2.5-pro" checked> gemini-2.5-pro</label>
          <label><input type="checkbox" name="app-model" value="gemini-3.8-flash-low" checked> gemini-3.8-flash-low</label>
          <label><input type="checkbox" name="app-model" value="gemini-3.8-flash-medium" checked> gemini-3.8-flash-med</label>
          <label><input type="checkbox" name="app-model" value="gemini-3.8-flash-high" checked> gemini-3.8-flash-high</label>
          <label><input type="checkbox" name="app-model" value="claude-sonnet-4-6"> claude-sonnet-4-6</label>
          <label><input type="checkbox" name="app-model" value="claude-opus-4-6-thinking"> claude-opus-4-6</label>
          <label><input type="checkbox" name="app-model" value="gpt-oss-120b-medium"> gpt-oss-120b</label>
        </div>
      </div>
      <div class="form-group">
        <label>Access Type</label>
        <select id="new-app-access">
          <option value="sandboxed_tools" selected>Sandboxed Tools (Workspace Only)</option>
          <option value="chat_only">Chat Only (No Execution)</option>
        </select>
      </div>
      <div class="form-group">
        <label>Allowed Origins (CORS Domain Whitelist)</label>
        <input type="text" id="new-app-origins" value="*" placeholder="* or https://myapp.com, http://localhost:3000">
        <small style="color: var(--text-muted); font-size: 0.75rem;">Leave * for all origins, or comma-separate trusted domains to restrict web clients.</small>
      </div>
      <div class="form-group" style="background:var(--bg-secondary); padding:10px; border-radius:6px; border:1px solid var(--border);">
        <label style="display:flex; align-items:center; gap:8px; cursor:pointer; text-transform:none; font-weight:600; color:white; margin-bottom:2px;">
          <input type="checkbox" id="new-app-vm" checked style="width:auto;">
          <span>⚡ Enable Safe Keyless Virtual Middleware Route</span>
        </label>
        <small style="color: var(--text-muted); font-size: 0.75rem;">Generates a secure high-entropy public slug so frontend apps can connect without storing secret API keys.</small>
      </div>
      <div style="display: flex; gap: 10px; margin-top: 20px;">
        <button class="btn-primary" onclick="submitCreateApp()">Create App</button>
        <button class="btn-secondary" onclick="closeCreateAppModal()">Cancel</button>
      </div>
    </div>
  </div>

  <script>
    const BASE_URL = window.location.origin;
    let currentUser = null;
    let userToken = localStorage.getItem('antigravity_user_token') || '';
    let currentApps = [];

    // Initialization
    async function init() {
      let loggedIn = false;
      if (userToken && userToken !== 'undefined' && userToken !== 'null') {
        loggedIn = await verifySession();
      }
      if (!loggedIn) {
        // Automatically attempt default admin login in background
        loggedIn = await autoLoginDefault();
      }
      if (!loggedIn) {
        openAuthModal();
      }
      fetchPendingApprovals();
      setInterval(fetchPendingApprovals, 5000);
    }

    async function autoLoginDefault() {
      try {
        const res = await fetch(`${BASE_URL}/v1/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: 'admin', password: 'admin' })
        });
        if (res.ok) {
          const data = await res.json();
          const token = data.token || data.user_token || (data.user && (data.user.token || data.user.user_token));
          if (token) {
            userToken = token;
            localStorage.setItem('antigravity_user_token', token);
            return await verifySession();
          }
        }
      } catch (e) {
        console.warn('Auto-login background attempt:', e);
      }
      return false;
    }

    async function quickAdminLogin() {
      document.getElementById('auth-username').value = 'admin';
      document.getElementById('auth-password').value = 'admin';
      await submitAuth(true);
    }

    async function verifySession() {
      if (!userToken || userToken === 'undefined' || userToken === 'null') {
        userToken = '';
        return false;
      }
      try {
        const res = await fetch(`${BASE_URL}/v1/auth/me`, {
          headers: { 'Authorization': `Bearer ${userToken}` }
        });
        if (res.ok) {
          currentUser = await res.json();
          document.getElementById('user-name').innerText = currentUser.username;
          document.getElementById('btn-auth-action').innerText = 'Logout';
          loadApps();
          loadTokenGuardPolicy();
          return true;
        } else {
          localStorage.removeItem('antigravity_user_token');
          userToken = '';
          currentUser = null;
          document.getElementById('user-name').innerText = 'Session Expired';
          document.getElementById('btn-auth-action').innerText = 'Login';
          return false;
        }
      } catch (e) {
        console.error('Session verify error:', e);
        return false;
      }
    }

    function handleAuthAction() {
      if (userToken) {
        localStorage.removeItem('antigravity_user_token');
        userToken = '';
        currentUser = null;
        document.getElementById('user-name').innerText = 'Logged Out';
        document.getElementById('btn-auth-action').innerText = 'Login';
        document.getElementById('apps-container').innerHTML = '<p style="color:var(--text-muted);">Please login to view applications.</p>';
      } else {
        openAuthModal();
      }
    }

    function openAuthModal() {
      const uInput = document.getElementById('auth-username');
      const pInput = document.getElementById('auth-password');
      if (uInput && !uInput.value) uInput.value = 'admin';
      if (pInput && !pInput.value) pInput.value = 'admin';
      const errBox = document.getElementById('auth-error-msg');
      if (errBox) errBox.style.display = 'none';
      document.getElementById('auth-modal').classList.add('active');
    }

    function closeAuthModal() {
      document.getElementById('auth-modal').classList.remove('active');
    }

    async function submitAuth(isLogin) {
      const u = document.getElementById('auth-username').value.trim();
      const p = document.getElementById('auth-password').value.trim();
      const errBox = document.getElementById('auth-error-msg');
      if (errBox) errBox.style.display = 'none';

      if (!u || !p) {
        const msg = 'Please enter username and password';
        if (errBox) { errBox.innerText = msg; errBox.style.display = 'block'; }
        else { alert(msg); }
        return;
      }

      const endpoint = isLogin ? '/v1/auth/login' : '/v1/auth/register';
      try {
        const res = await fetch(`${BASE_URL}${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: u, password: p })
        });
        const data = await res.json();
        if (res.ok) {
          const token = data.token || data.user_token || (data.user && (data.user.token || data.user.user_token));
          if (!token) {
            throw new Error('Authentication succeeded but server returned no token');
          }
          userToken = token;
          localStorage.setItem('antigravity_user_token', token);
          closeAuthModal();
          await verifySession();
        } else {
          const msg = data.detail || JSON.stringify(data);
          if (errBox) {
            errBox.innerText = 'Auth failed: ' + msg;
            errBox.style.display = 'block';
          } else {
            alert('Auth failed: ' + msg);
          }
        }
      } catch (e) {
        if (errBox) {
          errBox.innerText = 'Error: ' + e.message;
          errBox.style.display = 'block';
        } else {
          alert('Error: ' + e.message);
        }
      }
    }

    function switchTab(tabId) {
      document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
      document.getElementById('tab-' + tabId).classList.add('active');
      event.target.classList.add('active');
    }

    // Apps Management
    async function loadApps() {
      if (!userToken) return;
      try {
        const res = await fetch(`${BASE_URL}/v1/apps`, {
          headers: { 'Authorization': `Bearer ${userToken}` }
        });
        if (res.ok) {
          currentApps = await res.json();
          renderApps();
          populateAppSelectors();
        }
      } catch (e) {
        console.error('Error loading apps:', e);
      }
    }

    function renderApps() {
      const container = document.getElementById('apps-container');
      if (currentApps.length === 0) {
        container.innerHTML = `
          <div style="background:var(--bg-secondary); border:1px dashed var(--border); border-radius:var(--radius); padding:36px 20px; text-align:center;">
            <h4 style="margin-bottom:8px; color:white; font-size:1.1rem;">0 Applications Registered</h4>
            <p style="color:var(--text-muted); font-size:0.88rem; max-width:480px; margin:0 auto 18px; line-height:1.5;">
              Create your first App to generate an isolated profile with sliding-window rate limits, CORS domain whitelisting, and a safe keyless Virtual Middleware endpoint.
            </p>
            <button class="btn-primary" onclick="openCreateAppModal()">+ Create New App</button>
          </div>
        `;
        return;
      }

      container.innerHTML = currentApps.map(app => {
        const tokenPct = Math.min(100, Math.round((app.total_tokens_used / app.daily_token_limit) * 100));
        const modelBadges = (app.allowed_models || []).map(m => `<span class="tag" style="background:rgba(99,102,241,0.2); color:#a5b4fc; font-size:0.72rem;">${m}</span>`).join(' ');
        const origins = (app.allowed_origins || ['*']).join(', ');
        const vmUrl = `${BASE_URL}/p/${app.public_slug}/v1`;

        return `
          <div class="app-card">
            <div class="app-card-header">
              <div class="app-title">${app.name}</div>
              <button class="btn-danger" onclick="deleteApp('${app.id}')">Revoke</button>
            </div>
            <div class="app-tags">
              <span class="tag tag-rpm">${app.rate_limit_rpm} RPM</span>
              <span class="tag">Max Effort: ${app.max_effort}</span>
              <span class="tag" style="background:rgba(56,189,248,0.15); color:#38bdf8; border-color:rgba(56,189,248,0.3);">CORS: ${origins}</span>
              <span class="tag" style="background:rgba(16,185,129,0.15); color:var(--success); border-color:rgba(16,185,129,0.3);">Virtual Middleware: Active</span>
            </div>
            <div style="margin: 6px 0;">
              <div style="font-size:0.75rem; color:var(--text-muted); margin-bottom:4px;">Allowed Models:</div>
              <div style="display:flex; flex-wrap:wrap; gap:4px;">${modelBadges}</div>
            </div>
            <div>
              <div style="display:flex; justify-content:space-between; font-size:0.75rem; color:var(--text-muted); margin-bottom:2px;">
                <span>Daily Token Quota: ${app.total_tokens_used.toLocaleString()} / ${app.daily_token_limit.toLocaleString()}</span>
                <span>${tokenPct}%</span>
              </div>
              <div class="progress-bar-bg"><div class="progress-bar-fill" style="width: ${tokenPct}%;"></div></div>
            </div>

            <!-- Virtual Middleware Endpoint (Safe Keyless Route) -->
            <div style="background:rgba(99,102,241,0.1); border:1px solid rgba(99,102,241,0.3); border-radius:6px; padding:8px 10px; margin-top:4px;">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                <span style="font-size:0.75rem; font-weight:700; color:#a5b4fc;">🛡️ Safe Keyless Endpoint:</span>
                <button class="btn-secondary" style="padding:2px 8px; font-size:0.72rem;" onclick="copyText('${vmUrl}')">Copy URL</button>
              </div>
              <div style="font-family:monospace; font-size:0.76rem; color:#38bdf8; word-break:break-all;">${vmUrl}</div>
              <small style="color:var(--text-muted); font-size:0.7rem;">Use in client apps — zero secret keys required!</small>
            </div>

            <!-- Standard Secret API Key -->
            <div class="key-box">
              <span title="${app.api_key}">${app.api_key.length > 20 ? app.api_key.slice(0, 16) + '••••••••' : app.api_key}</span>
              <div style="display:flex; gap:4px;">
                <button class="btn-secondary" style="padding:2px 8px; font-size:0.75rem;" onclick="copyText('${app.api_key}')">Copy Key</button>
                <button class="btn-secondary" style="padding:2px 8px; font-size:0.75rem;" onclick="promptEditKey('${app.id}', '${app.api_key}')">Edit</button>
              </div>
            </div>
          </div>
        `;
      }).join('');
    }

    function populateAppSelectors() {
      const chatSel = document.getElementById('chat-app-selector');
      const connSel = document.getElementById('connect-app-selector');

      const options = currentApps.map(a => `<option value="${a.api_key}" data-id="${a.id}">${a.name} (${a.rate_limit_rpm} RPM)</option>`).join('');
      chatSel.innerHTML = options || '<option value="">0 apps created</option>';
      connSel.innerHTML = options || '<option value="">0 apps created</option>';
      updateChatModelOptions();
      renderAppConnectionGuide();
    }

    function updateChatModelOptions() {
      const chatSel = document.getElementById('chat-app-selector');
      const modelSel = document.getElementById('chat-model');
      const selectedKey = chatSel.value;
      const app = currentApps.find(a => a.api_key === selectedKey);

      if (app && app.allowed_models && app.allowed_models.length > 0) {
        modelSel.innerHTML = app.allowed_models.map(m => `<option value="${m}">${m}</option>`).join('');
      } else {
        modelSel.innerHTML = `
          <option value="gemini-2.5-flash" selected>Gemini 2.5 Flash</option>
          <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
          <option value="gemini-3.8-flash-low">Gemini 3.8 Flash (Low)</option>
          <option value="gemini-3.8-flash-medium">Gemini 3.8 Flash (Med)</option>
          <option value="gemini-3.8-flash-high">Gemini 3.8 Flash (High)</option>
        `;
      }
    }

    async function promptEditKey(appId, oldKey) {
      const newKey = prompt('Enter manual/custom API key for this app:', oldKey);
      if (!newKey || newKey.trim() === oldKey) return;

      try {
        const res = await fetch(`${BASE_URL}/v1/apps/${appId}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${userToken}`
          },
          body: JSON.stringify({ api_key: newKey.trim() })
        });
        if (res.ok) {
          alert('API Key updated successfully!');
          loadApps();
        } else {
          alert('Failed to update API key: ' + await res.text());
        }
      } catch (e) {
        alert('Error: ' + e.message);
      }
    }

    function openCreateAppModal() { document.getElementById('create-app-modal').classList.add('active'); }
    function closeCreateAppModal() { document.getElementById('create-app-modal').classList.remove('active'); }

    async function submitCreateApp() {
      const name = document.getElementById('new-app-name').value.trim();
      const rpm = parseInt(document.getElementById('new-app-rpm').value) || 15;
      const tokens = parseInt(document.getElementById('new-app-tokens').value) || 500000;
      const effort = document.getElementById('new-app-effort').value;
      const access = document.getElementById('new-app-access').value;
      const customKey = document.getElementById('new-app-key').value.trim() || null;
      const originsRaw = document.getElementById('new-app-origins').value.trim();
      const origins = originsRaw ? originsRaw.split(',').map(s => s.trim()).filter(Boolean) : ['*'];
      const vmEnabled = document.getElementById('new-app-vm').checked ? 1 : 0;

      const checkedModels = Array.from(document.querySelectorAll('input[name="app-model"]:checked')).map(cb => cb.value);
      const allowedModels = checkedModels.length > 0 ? checkedModels : ["gemini-2.5-flash"];

      if (!name) return alert('Enter an App name');

      try {
        const bodyPayload = {
          name,
          rate_limit_rpm: rpm,
          daily_token_limit: tokens,
          max_effort: effort,
          access_type: access,
          allowed_models: allowedModels,
          allowed_origins: origins,
          enable_virtual_middleware: vmEnabled
        };
        if (customKey) {
          bodyPayload.api_key = customKey;
        }

        const res = await fetch(`${BASE_URL}/v1/apps`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${userToken}`
          },
          body: JSON.stringify(bodyPayload)
        });
        if (res.ok) {
          closeCreateAppModal();
          document.getElementById('new-app-key').value = '';
          loadApps();
        } else {
          alert('Failed to create app: ' + await res.text());
        }
      } catch (e) {
        alert('Error: ' + e.message);
      }
    }

    async function deleteApp(appId) {
      if (!confirm('Are you sure you want to revoke this application key?')) return;
      try {
        const res = await fetch(`${BASE_URL}/v1/apps/${appId}`, {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${userToken}` }
        });
        if (res.ok) loadApps();
      } catch (e) {
        alert('Error deleting app: ' + e.message);
      }
    }

    // Token Guard Policy
    async function loadTokenGuardPolicy() {
      if (!userToken) return;
      try {
        const res = await fetch(`${BASE_URL}/v1/token-guard`, {
          headers: { 'Authorization': `Bearer ${userToken}` }
        });
        if (res.ok) {
          const p = await res.json();
          document.getElementById('guard-max-prompt').value = p.max_prompt_chars || 10000;
          document.getElementById('guard-max-effort').value = p.max_reasoning_effort || 'medium';
        }
      } catch (e) {
        console.error(e);
      }
    }

    async function saveTokenGuardPolicy() {
      if (!userToken) return;
      try {
        const res = await fetch(`${BASE_URL}/v1/token-guard`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${userToken}`
          },
          body: JSON.stringify({
            max_prompt_chars: parseInt(document.getElementById('guard-max-prompt').value),
            max_reasoning_effort: document.getElementById('guard-max-effort').value,
            expensive_model_policy: 'require_approval',
            block_high_effort: 0,
            daily_system_token_cap: 2000000
          })
        });
        if (res.ok) alert('Token guardrails saved successfully!');
        else alert('Error: ' + await res.text());
      } catch (e) {
        alert('Error: ' + e.message);
      }
    }

    // Approvals Management
    async function fetchPendingApprovals() {
      if (!userToken) return;
      const listEl = document.getElementById('approvals-list');
      const badge = document.getElementById('approvals-badge');

      try {
        const res = await fetch(`${BASE_URL}/v1/approvals/pending`, {
          headers: { 'Authorization': `Bearer ${userToken}` }
        });
        if (!res.ok) return;

        const items = await res.json();
        badge.innerText = items.length;
        badge.style.display = items.length > 0 ? 'inline' : 'none';

        if (items.length === 0) {
          listEl.innerHTML = '<p style="color:var(--text-muted); font-size:0.9rem;">No actions currently waiting for approval.</p>';
          return;
        }

        listEl.innerHTML = items.map(item => `
          <div style="background:var(--bg-secondary); border:1px solid rgba(239, 68, 68, 0.4); border-radius:var(--radius); padding:16px; margin-bottom:12px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
              <strong style="color:var(--warning);">Ticket #${item.id.slice(0, 8)}</strong>
              <span class="tag tag-danger">${item.reason}</span>
            </div>
            <p style="font-family:monospace; background:rgba(0,0,0,0.3); padding:8px; border-radius:4px; margin:8px 0; font-size:0.85rem;">${item.prompt}</p>
            <div style="display:flex; gap:10px; margin-top:10px;">
              <button class="btn-primary" style="background:var(--success); flex:1;" onclick="resolveApproval('${item.id}', 'approve')">Approve Execution</button>
              <button class="btn-primary" style="background:var(--danger); flex:1;" onclick="resolveApproval('${item.id}', 'deny')">Block / Deny</button>
            </div>
          </div>
        `).join('');
      } catch (e) {
        console.error(e);
      }
    }

    async function resolveApproval(id, decision) {
      try {
        const res = await fetch(`${BASE_URL}/v1/approvals/${id}/respond`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${userToken}`
          },
          body: JSON.stringify({ decision })
        });
        if (res.ok) fetchPendingApprovals();
      } catch (e) {
        alert('Error: ' + e.message);
      }
    }

    // Chat
    function clearChat() {
      document.getElementById('chat-messages').innerHTML = '<div class="msg" style="align-self:center; color:var(--text-muted);">Chat cleared.</div>';
    }

    function handleChatKeyDown(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
      }
    }

    async function sendChatMessage() {
      const textarea = document.getElementById('chat-prompt-input');
      const prompt = textarea.value.trim();
      const appKey = document.getElementById('chat-app-selector').value;

      if (!prompt) return;
      if (!appKey) return alert('Select or create an App first');

      textarea.value = '';
      const chatContainer = document.getElementById('chat-messages');

      const userBubble = document.createElement('div');
      userBubble.className = 'msg user';
      userBubble.innerText = prompt;
      chatContainer.appendChild(userBubble);

      const agentBubble = document.createElement('div');
      agentBubble.className = 'msg agent';
      agentBubble.innerText = 'Evaluating safety & thinking...';
      chatContainer.appendChild(agentBubble);
      chatContainer.scrollTop = chatContainer.scrollHeight;

      const payload = {
        message: prompt,
        model: document.getElementById('chat-model').value,
        effort: document.getElementById('chat-effort').value,
        require_approval: document.getElementById('chat-force-approval').checked
      };

      try {
        const response = await fetch(`${BASE_URL}/v1/chat/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${appKey}`
          },
          body: JSON.stringify(payload)
        });

        if (!response.ok) {
          const err = await response.text();
          agentBubble.innerText = `[Denied ${response.status}]: ${err}`;
          agentBubble.style.borderColor = 'var(--danger)';
          return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        agentBubble.innerText = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split('\\n');

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const dataStr = line.slice(6).trim();
              if (dataStr === '[DONE]') break;
              try {
                const parsed = JSON.parse(dataStr);
                if (parsed.event === 'approval_required') {
                  agentBubble.innerText += `\\n[⚠️ Token Drain Guard: Ticket #${parsed.approval_id} - ${parsed.reason}]\\nWaiting for approval...\\n`;
                  fetchPendingApprovals();
                } else if (parsed.event === 'approval_granted') {
                  agentBubble.innerText += `\\n[✅ Approved. Streaming tokens...]\\n`;
                } else if (parsed.event === 'approval_rejected') {
                  agentBubble.innerText += `\\n[❌ Execution denied.]\\n`;
                } else {
                  agentBubble.innerText += dataStr;
                }
              } catch (e) {
                agentBubble.innerText += dataStr;
              }
              chatContainer.scrollTop = chatContainer.scrollHeight;
            }
          }
        }
      } catch (err) {
        agentBubble.innerText = `[Network Error]: ${err.message}`;
      }
    }

    // How to Connect Guide
    function renderAppConnectionGuide() {
      const sel = document.getElementById('connect-app-selector');
      const selectedKey = sel.value;
      const app = currentApps.find(a => a.api_key === selectedKey) || currentApps[0];

      if (!app) {
        document.getElementById('vm-url-code').innerText = 'Please create an application first.';
        document.getElementById('vm-py-code').innerText = '# 0 applications registered. Click "+ Create New App" to generate connection code.';
        document.getElementById('vm-js-code').innerText = '// 0 applications registered.';
        document.getElementById('openwebui-url').innerText = `${BASE_URL}/v1`;
        document.getElementById('openwebui-key').innerText = 'No API keys';
        document.getElementById('curl-app-code').innerText = '# Create an App first';
        document.getElementById('nextjs-route-code').innerText = '// Create an App first';
        document.getElementById('cf-worker-code').innerText = '// Create an App first';
        return;
      }

      const key = app.api_key;
      const vmUrl = `${BASE_URL}/p/${app.public_slug}/v1`;
      const model = (app.allowed_models && app.allowed_models[0]) || 'gemini-2.5-flash';

      document.getElementById('vm-url-code').innerText = vmUrl;
      document.getElementById('vm-py-code').innerText = `from openai import OpenAI\n\n# 🛡️ Safe Keyless Virtual Middleware (Zero secret keys in app code!)\nclient = OpenAI(\n    base_url="${vmUrl}",\n    api_key="none"  # No secret key needed\n)\n\nresponse = client.chat.completions.create(\n    model="${model}",\n    messages=[{"role": "user", "content": "Hello!"}],\n    stream=True\n)\nfor chunk in response:\n    print(chunk.choices[0].delta.content or "", end="")`;

      document.getElementById('vm-js-code').innerText = `import OpenAI from "openai";\n\n// 🛡️ Safe Keyless Virtual Middleware (Zero secret keys in client!)\nconst client = new OpenAI({\n  baseURL: "${vmUrl}",\n  apiKey: "none",\n  dangerouslyAllowBrowser: true\n});\n\nconst stream = await client.chat.completions.create({\n  model: "${model}",\n  messages: [{ role: "user", content: "Hello!" }],\n  stream: true\n});\n\nfor await (const chunk of stream) {\n  process.stdout.write(chunk.choices[0]?.delta?.content || "");\n}`;

      document.getElementById('openwebui-url').innerText = `${BASE_URL}/v1`;
      document.getElementById('openwebui-key').innerText = key;
      document.getElementById('curl-app-code').innerText = `curl -N -X POST "${BASE_URL}/v1/chat/completions" \\\n  -H "Authorization: Bearer ${key}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "${model}", "messages": [{"role": "user", "content": "Hello!"}], "stream": true}'`;

      document.getElementById('nextjs-route-code').innerText = `// app/api/chat/route.ts (Next.js Edge Proxy)\nimport { OpenAI } from "openai";\n\nconst client = new OpenAI({\n  baseURL: "${BASE_URL}/v1",\n  apiKey: process.env.ANTIGRAVITY_API_KEY || "${key}"\n});\n\nexport async function POST(req: Request) {\n  const { messages } = await req.json();\n  const stream = await client.chat.completions.create({\n    model: "${model}",\n    messages,\n    stream: true\n  });\n  return new Response(stream.toReadableStream());\n}`;

      document.getElementById('cf-worker-code').innerText = `// Cloudflare Worker (Free Serverless Edge Middleware)\nexport default {\n  async fetch(request, env) {\n    const target = "${BASE_URL}/v1/chat/completions";\n    const headers = new Headers(request.headers);\n    headers.set("Authorization", "Bearer ${key}");\n    return fetch(target, { method: request.method, headers, body: request.body });\n  }\n};`;
    }

    function copySnippet(elementId) {
      const text = document.getElementById(elementId).innerText;
      copyText(text);
    }

    function copyText(str) {
      navigator.clipboard.writeText(str);
      alert('Copied to clipboard!');
    }

    init();
  </script>
</body>
</html>
"""
