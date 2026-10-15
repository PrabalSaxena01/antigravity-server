# Master Instruction Guide: Antigravity Virtual Middleware & Client Setup

This folder contains step-by-step instructions for managing, connecting, and securing client applications with your hardened Antigravity Server.

---

## 📚 Guide Index

| File | Topic | Description |
| :--- | :--- | :--- |
| [**`01_QUICK_START_CONNECT_NEW_APP.md`**](file:///D:/Nokia_Interview_Prep/Instruction/01_QUICK_START_CONNECT_NEW_APP.md) | **Step-by-step Quick Start** | How to create an app in the dashboard, copy the Keyless Virtual Middleware URL, and integrate it into Python/Node.js with zero keys. |
| [**`02_CORS_AND_WEBAPP_GUIDE.md`**](file:///D:/Nokia_Interview_Prep/Instruction/02_CORS_AND_WEBAPP_GUIDE.md) | **Web Applications & CORS** | Detailed domain whitelisting, browser security mechanics, and full frontend JS/React streaming code. |
| [**`03_SECURITY_AND_EXTERNAL_NETWORK.md`**](file:///D:/Nokia_Interview_Prep/Instruction/03_SECURITY_AND_EXTERNAL_NETWORK.md) | **Security & Network Architecture** | How your server defends itself against outside network traffic, DoS attacks, unauthorized scrapers, and bot floods. |

---

## 🛡️ Core Architectural Principle: Zero Client Keys

```
+-------------------------------------------------------+
|                   Client Device                       |
|   (Web Browser, Python Script, or Mobile App)         |
|                                                       |
|   client = OpenAI(                                    |
|       base_url="https://<tunnel>/p/pub_xxxx/v1",     |
|       api_key="none"  <-- ZERO SECRET KEYS STORED     |
|   )                                                   |
+---------------------------+---------------------------+
                            |
                   HTTPS (Encrypted)
                            |
                            v
+-------------------------------------------------------+
|             Cloudflare Edge Network                   |
|   - SSL / HTTPS Termination                           |
|   - DDoS Mitigation & Bot Fight Shield                |
+---------------------------+---------------------------+
                            |
                     Tunnel Ingress
                            |
                            v
+-------------------------------------------------------+
|             Antigravity Server (Phone/Host)           |
|                                                       |
|   1. CORS Whitelist Verification (Web Browsers)      |
|   2. 2 MB DoS Request Body Cap Check                  |
|   3. Cryptographic Slug Matching (`pub_...`)          |
|   4. Per-App Rate Limiting Throttling (429)           |
|   5. Streaming Execution via Antigravity Engine       |
+-------------------------------------------------------+
```

---

## ⚡ Quick Rules of Thumb

1. **Never copy or embed the secret API key into client code.**
   Always use the **Keyless Virtual Middleware URL** (`/p/pub_.../v1`).
2. **If your client is a Web Browser (React/Vue/HTML):**
   Enter your website's origin in the **Allowed Origins** box (e.g. `https://my-app.vercel.app`).
3. **If your client is a Python script, Backend, or Mobile App:**
   Leave Allowed Origins as `*`.
