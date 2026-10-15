# 01 - Quick Start: Connecting a New Application

This guide walks you through connecting any new client application (Python, Node.js, CLI, or Backend) to your Antigravity Server using the **Safe Keyless Virtual Middleware URL**.

---

## Step 1: Create the Application in Web Dashboard

1. Open your browser and navigate to your dashboard:
   - Locally: `http://localhost:8000`
   - Over Cloudflare Tunnel: `https://<your-tunnel>.trycloudflare.com`
2. Log in using your master admin password.
3. Click the blue **`+ Create New App`** button.
4. Configure the app parameters:
   - **App Name**: Give it an identifier (e.g. `Data Analysis Agent`, `Telegram Bot`, `Desktop Client`).
   - **Rate Limit**: Set maximum requests per minute (e.g. `30` or `60`).
   - **Allowed Origins**: Leave as `*` for non-browser apps (Python/Node/mobile).
   - **Enable Keyless Virtual Middleware Route**: Ensure this checkbox is checked (default is ON).
5. Click **Create Application**.

---

## Step 2: Copy the Safe Keyless Endpoint

1. Locate your app's card under **Registered Applications**.
2. Look for the section labeled **🛡️ Safe Keyless Endpoint**.
3. Click **Copy URL** (or copy the text). It will look like this:
   ```text
   https://<your-tunnel-domain>.trycloudflare.com/p/pub_4f8a29c1e7/v1
   ```

> [!CAUTION]
> **Do NOT copy the secret API key.**
> The Virtual Middleware route handles authorization automatically via the high-entropy slug (`pub_...`). You do not need or want an API key stored on your client device.

---

## Step 3: Implement in Your Client App

### Option A: Python (`openai>=1.0.0`)

```python
from openai import OpenAI

# 1. Initialize client with your Keyless Virtual Middleware URL
client = OpenAI(
    base_url="https://<your-tunnel-domain>.trycloudflare.com/p/pub_4f8a29c1e7/v1",
    api_key="none"  # No secret key needed! Virtual middleware validates via path.
)

# 2. Make completion call with streaming
response = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=[
        {"role": "system", "content": "You are a professional assistant."},
        {"role": "user", "content": "Explain quantum entanglement in 2 sentences."}
    ],
    stream=True
)

for chunk in response:
    content = chunk.choices[0].delta.content or ""
    print(content, end="", flush=True)
```

---

### Option B: Node.js / JavaScript (OpenAI SDK)

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "https://<your-tunnel-domain>.trycloudflare.com/p/pub_4f8a29c1e7/v1",
  apiKey: "none" // No secret key needed
});

async function run() {
  const stream = await client.chat.completions.create({
    model: "gemini-2.5-pro",
    messages: [{ role: "user", content: "Hello from Node.js client!" }],
    stream: true,
  });

  for await (const chunk of stream) {
    process.stdout.write(chunk.choices[0]?.delta?.content || "");
  }
}

run();
```

---

### Option C: cURL / Raw HTTP

```bash
curl -X POST "https://<your-tunnel-domain>.trycloudflare.com/p/pub_4f8a29c1e7/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [
      {"role": "user", "content": "Say hello!"}
    ],
    "stream": false
  }'
```

---

## Step 4: Verification

When you execute your script:
1. The client makes a `POST` request directly to your Cloudflare Tunnel.
2. The server recognizes the public slug, confirms rate-limit limits, and executes Antigravity CLI.
3. Server-Sent Events (SSE) or full JSON response is returned directly to your client.
4. Check your server terminal: you will see real-time log output verifying the connection.
