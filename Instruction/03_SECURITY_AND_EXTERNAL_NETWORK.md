# 03 - Security & External Network Protection

This document outlines how your Antigravity Server protects itself when exposed to the open internet via Cloudflare Tunnel, and how requests from outside your network are handled safely.

---

## 1. Network Traffic Overview

When your server is exposed through Cloudflare, it is reachable by any client in the world that knows the tunnel address. Here is how different incoming requests are handled:

| Request Type | Origin Header Present? | Primary Defense Layer | Result |
| :--- | :--- | :--- | :--- |
| **Legitimate Web App** | Yes (`https://myapp.com`) | CORS Domain Whitelist | Allowed (200 OK / 204 No Content) |
| **Unauthorized Web App** | Yes (`https://evil-site.com`) | CORS Domain Whitelist | Blocked (**403 Forbidden**) |
| **Legitimate Backend / Script** | No | 128-bit Slug Entropy + Rate Limit | Allowed (up to rate limit) |
| **Malicious Bot / Scraper** | No / Random | Slug Entropy + Rate Limit + DoS Body Limit | Blocked or Throttled (**404**, **413**, **429**) |
| **Password Brute Force** | N/A | IP Lockout (5 attempts / 5 mins) | Blocked (**429 Too Many Requests**) |

---

## 2. The 5 Built-in Defense Layers

### Layer 1: Cryptographic Slug Entropy (`pub_...`)
- Every application receives a high-entropy 128-bit random token (32 hexadecimal characters):
  `pub_7b1d3e8a9f20c41b65e9083f2a5d12cb`
- Guessing a valid slug by brute force requires $2^{128}$ attempts (astronomically impossible).
- Requests to nonexistent slugs receive an immediate `404 Not Found` without running any CLI or background processes.

### Layer 2: Strict CORS Whitelisting
- When a web browser connects, the server checks the `Origin` header against the JSON whitelist in your SQLite database.
- If the domain does not match, the request terminates immediately with `403 Forbidden` before any compute or subprocess resources are allocated.

### Layer 3: Per-App Leaky Bucket Rate Limiting
- Each registered app has a distinct rate limit (e.g. 30 requests/minute).
- If any external client floods the API, subsequent requests are throttled with `429 Too Many Requests` with a `Retry-After: 60` header.

### Layer 4: DoS Request Body Protection
- The server limits all incoming request payloads to a strict **2 MB maximum** (`MAX_BODY_SIZE`).
- Payloads exceeding 2 MB are aborted at the socket level with **`413 Payload Too Large`**, preventing memory exhaustion on lightweight devices (such as mobile phones running Termux or single-board computers).

### Layer 5: Path Traversal & Subprocess Lifecycle Guard
- All conversation IDs are strictly validated with the regex `^[a-zA-Z0-9_\-]{4,128}$`. Any attempt to insert `../` or relative paths is rejected with `400 Bad Request`.
- If an external client terminates the connection mid-stream, a Python `finally:` block terminates and cleans up the underlying Antigravity subprocess immediately, preventing CPU spikes or battery drain.

---

## 3. Optional: Extra Cloudflare Edge Protections

If you want an additional layer of security before traffic even reaches your device, configure these free settings in your Cloudflare dashboard:

1. **Bot Fight Mode**:
   - Go to **Security > Bots** in Cloudflare.
   - Turn on **Bot Fight Mode**. Cloudflare will automatically challenge and block known malicious scrapers and botnets at the edge.
2. **Geo-Blocking / Country Restriction**:
   - Go to **Security > WAF > Custom Rules**.
   - Create a rule: *If Country is not equal to [Your Country], Block*.
   - Traffic from other countries will be blocked by Cloudflare without touching your local network or server.
3. **Cloudflare Zero Trust / Access (Optional for Admin Dashboard)**:
   - You can place an email one-time PIN (OTP) or Google OAuth gate in front of your admin dashboard path (`/`) while leaving your virtual middleware (`/p/*`) open for your apps.
