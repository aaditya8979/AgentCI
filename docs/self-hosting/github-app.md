# GitHub App Setup

Step-by-step guide to creating and installing the AgentCI GitHub App.

!!! tip "Already deployed?"
    If you just want to use AgentCI without self-hosting, install the public app: [Install AgentCI](https://github.com/apps/agent-ci-aaditya)

## 1. Create the App

Go to **[github.com/settings/apps/new](https://github.com/settings/apps/new)**

Fill in:

| Field | Value |
|-------|-------|
| **App name** | `AgentCI` (must be globally unique) |
| **Homepage URL** | `http://localhost:3000` |
| **Webhook URL** | `https://YOUR-NGROK-URL/webhook/github` |
| **Webhook secret** | Generate: `openssl rand -hex 20` |

## 2. Set Permissions

Under **Repository permissions**:

| Permission | Access |
|------------|--------|
| **Checks** | Read & write |
| **Contents** | Read-only |
| **Metadata** | Read-only |
| **Pull requests** | Read & write |

## 3. Subscribe to Events

Check: **Pull request**

## 4. Create and Note Credentials

After creating:

1. Note the **App ID** (top of page)
2. Click **Generate a private key** → download the `.pem` file
3. Click **Install App** → install on your repo
4. Note the **Installation ID** from the URL

## 5. Configure AgentCI

Add to your `.env`:

```bash
GITHUB_APP_ID=123456
GITHUB_INSTALLATION_ID=12345678

# Convert private key to single line:
# awk 'NF {sub(/\r/, ""); printf "%s\\n", $0}' your-key.pem
GITHUB_APP_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----
```

Restart:

```bash
cd docker && docker compose restart api worker
```

## 6. Verify

```bash
./scripts/verify_webhook.sh
```

All 11 tests should pass. Check **GitHub App → Advanced → Recent Deliveries** for the ping event.
