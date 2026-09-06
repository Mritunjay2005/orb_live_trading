# CI/CD Setup — Auto Deploy to Production

After this is configured, every `git push` to `main` will:

1. Run CI (lint/syntax)
2. Build & push Docker image to GHCR (existing `build.yml`)
3. **SSH into the OCI server, pull latest code, rebuild & restart containers** (new `deploy.yml`)

You do **not** need to run `docker-compose` on the server manually for normal updates.

---

## 1. GitHub Secrets (required)

In GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Create these three secrets:

| Secret name | Value |
|-------------|--------|
| `OCI_HOST` | `80.225.255.207` |
| `OCI_USER` | `ubuntu` |
| `OCI_SSH_PRIVATE_KEY` | Full contents of your SSH **private** key |

### How to copy the private key (on your laptop, Git Bash)

```bash
cat ~/.ssh/id_ed25519
```

Copy **everything**, including:

```text
-----BEGIN OPENSSH PRIVATE KEY-----
...
-----END OPENSSH PRIVATE KEY-----
```

Paste that entire block as the value of `OCI_SSH_PRIVATE_KEY`.

**Never commit this key to the repo.**

---

## 2. Push the deploy workflow

On your laptop:

```bash
cd /y/TRADING_SETUP/orb_live_trading

# If deploy.yml is not already there, copy it into:
# .github/workflows/deploy.yml

git add .github/workflows/deploy.yml CI_CD_SETUP.md
git commit -m "Add automatic deploy to OCI on push to main"
git push
```

The first push will trigger the new workflow. Check:

**GitHub → Actions tab** → workflow **Deploy to OCI Production**

---

## 3. Server prerequisite (one-time)

The server must be able to `git pull` without a password.

On the server (SSH in once):

```bash
cd /opt/orb_live_trading
git status
git remote -v
```

If the remote is HTTPS and pulls ask for credentials, switch to a deploy-friendly setup:

### Option A — Keep HTTPS + credential (simple for private repo)

Create a GitHub **fine-grained** or classic PAT with `repo` read access, then on server:

```bash
cd /opt/orb_live_trading
git remote set-url origin https://YOUR_GITHUB_USERNAME:YOUR_PAT@github.com/Mritunjay2005/orb_live_trading.git
```

### Option B — Deploy key (more secure)

1. On server: `ssh-keygen -t ed25519 -f ~/.ssh/deploy_key -N ""`
2. `cat ~/.ssh/deploy_key.pub` → add as **Deploy key** (read-only) in GitHub repo Settings → Deploy keys
3. Configure git to use that key for github.com

Option A is faster to set up.

Also ensure the `ubuntu` user can run docker without sudo (already done via `usermod -aG docker`).

---

## 4. How a normal update works after setup

On laptop:

```bash
cd /y/TRADING_SETUP/orb_live_trading
# edit main.py or any file
git add .
git commit -m "my change"
git push
```

Then automatically:
- GitHub Actions checks out nothing on deploy job (SSH only)
- SSHs to `80.225.255.207` as `ubuntu`
- Runs `git fetch` + `git reset --hard origin/main`
- Runs `docker-compose up -d --build`
- Restarts updated containers

Watch progress: **GitHub → Actions**

---

## 5. Manual deploy (optional)

**GitHub → Actions → Deploy to OCI Production → Run workflow**

Useful if you want to redeploy without a new commit.

---

## 6. Troubleshooting

| Problem | Fix |
|---------|-----|
| Deploy job fails: Permission denied (publickey) | `OCI_SSH_PRIVATE_KEY` must be the **private** key that matches the public key on the server (`~/.ssh/authorized_keys`) |
| Deploy fails: Host key verification | Re-run; `appleboy/ssh-action` usually handles this. Ensure host is correct |
| git pull fails on server | Fix remote URL / PAT (see section 3) |
| docker permission denied on server | `sudo usermod -aG docker ubuntu` and reconnect |
| Workflow did not start | File must be on branch `main` under `.github/workflows/deploy.yml` |

---

## 7. Security notes

- SSH key in GitHub Secrets is encrypted at rest
- Prefer a dedicated deploy key with limited scope if you harden later
- `LIVE_TRADING` still controlled only by server `.env` (not overwritten by git if `.env` is gitignored — which it is)
- `.env` is in `.gitignore` → production secrets on server are **not** replaced by push

---

## Flow diagram

```text
Laptop: edit code
    → git push origin main
        → GitHub Actions: CI
        → GitHub Actions: Build image (GHCR)
        → GitHub Actions: Deploy
              → SSH ubuntu@80.225.255.207
              → git reset --hard origin/main
              → docker-compose up -d --build
              → production updated
```
EOF
