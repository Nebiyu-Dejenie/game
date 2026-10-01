# SSH access as `ssh.arada.click`

**Status (2026-10-01): step 1 done. Blocked on step 2: the server accepts password logins**
(`ssh -o PreferredAuthentications=none cosmic@192.168.1.115` answers
`Permission denied (publickey,password)`). So `99-officos.conf`'s
`PasswordAuthentication no` is being overridden, as feared below. The DNS
record (step 4) stays unpublished until a re-check shows `(publickey)` only,
because publishing first would put password-guessable SSH on the internet.
Goal: `ssh cosmic@ssh.arada.click` from anywhere, instead of only from the
server's LAN (`192.168.1.115`), and without opening port 22 to the internet.

## What was found (read-only inspection, 2026-10-01)

| | Finding |
|---|---|
| DNS | `arada.click` is on Cloudflare (`dane`/`teresa.ns.cloudflare.com`), records proxied. `ssh.arada.click` had no record. |
| Network | The server is a VM on a LAN (`enp6s18`, `192.168.1.115/24`) behind a router. The network's public IP is `196.191.95.113`. All web traffic already arrives through a Cloudflare Tunnel, so nothing is port-forwarded. |
| Tunnel | A locally managed named tunnel `30a80298-fa2a-4c8a-9c86-63fdad9cb85e`, running as the `cloudflared` container. Its routing is in `deploy/cloudflared/config.yml` on the server (gitignored; this repo has `config.yml.example`). The origin certificate `~/.cloudflared/cert.pem` is present, so DNS routes can be created from the server. |
| sshd | OpenSSH 9.6 on Ubuntu 24.04.5, listening on `0.0.0.0:22` and `[::]:22`. `99-officos.conf` sets `PermitRootLogin no`, `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `MaxAuthTries 3`. `50-cloud-init.conf` can't be read without root, and **sshd takes the first value it reads, in file-name order**, so a `PasswordAuthentication yes` there would win. Step 2 checks this. |
| Firewall | UFW status needs root (step 2). From the tunnel's Docker network, the host's sshd is reachable at both `172.19.0.1:22` and `172.17.0.1:22`. |
| Host key | ED25519 `SHA256:KlYJk3l+8I/7xzvQdu8OyW6O1WRzKIgoOjL3HEvwbn0` (also ECDSA `SHA256:Id8dyTK/…`, RSA `SHA256:7hJYN8o1…`). |

## Why a tunnel, not a DNS record to the public IP

- **Normal Cloudflare DNS can't carry SSH.** A proxied record (orange cloud)
  only passes HTTP(S).
- **A DNS-only record (grey cloud) would mean exposing SSH.** It would point
  at `196.191.95.113` and need the router to forward port 22 to the server,
  putting sshd in front of the whole internet. That means constant
  password-guessing and exploit scanning, and the home IP becomes public in
  DNS. It may not even work if the ISP uses carrier-grade NAT.
- **The tunnel is already running and outbound-only.** A
  `hostname → ssh://` rule in it, plus a **Cloudflare Access** policy,
  means nobody reaches sshd without first logging in to Cloudflare as an
  allowed identity. Only then do they face sshd's key-only authentication.
  **No port is opened on the router or in UFW.**

## Steps

### 1. Tunnel route: done (2026-10-01 12:17 UTC)

Added to the live `config.yml`, before the `http_status:404` catch-all
(backup `config.yml.bak-20261001T121645Z` beside it):
```yaml
  - hostname: ssh.arada.click
    service: ssh://172.17.0.1:22
```
- `cloudflared tunnel --config config.yml ingress validate` gave OK, and
  `ingress rule ssh://ssh.arada.click` matched rule #8.
- The container was restarted when no real player was in an open Bingo
  round. `/healthz` was back to 200 within 3 s, 4 tunnel connections
  registered, and the admin, payments, agent, finance and SMS hostnames all
  answer.
- **The route is inert:** nothing reaches it until step 4 creates the DNS
  record.

### 2. Operator: check sshd and the firewall (needs `sudo`)

**One block to paste** (on the server, from a session you keep open). It
backs up `/etc/ssh`, makes the hardening file sort first so it wins,
validates before reloading, and reverts itself if validation fails:
```bash
sudo bash -c '
set -e
B=/root/ssh-backup-$(date +%Y%m%d-%H%M%S); cp -a /etc/ssh "$B"; echo "backup: $B"
grep -iE "^[[:space:]]*PasswordAuthentication" /etc/ssh/sshd_config.d/50-cloud-init.conf || true
mv /etc/ssh/sshd_config.d/99-officos.conf /etc/ssh/sshd_config.d/01-officos.conf
if sshd -t; then systemctl reload ssh; else
  mv /etc/ssh/sshd_config.d/01-officos.conf /etc/ssh/sshd_config.d/99-officos.conf; echo "sshd -t failed: reverted"; exit 1; fi
sshd -T | grep -Ei "^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin|pubkeyauthentication|maxauthtries) "
ufw status verbose
'
```
Expected last lines: `passwordauthentication no`, `kbdinteractiveauthentication no`,
`permitrootlogin no`, `pubkeyauthentication yes`, `maxauthtries 3`.
Re-check without root: `ssh -o PreferredAuthentications=none -o PubkeyAuthentication=no cosmic@192.168.1.115`
must now answer `Permission denied (publickey).`

The same steps, one at a time:

Keep your current SSH session open throughout, so a mistake can't lock you
out.
```bash
sudo cp -a /etc/ssh /root/ssh-backup-$(date +%Y%m%d-%H%M%S)        # backup first
sudo sshd -T | grep -Ei '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin|pubkeyauthentication|maxauthtries) '
sudo cat /etc/ssh/sshd_config.d/50-cloud-init.conf
```
Expected: `passwordauthentication no`, `kbdinteractiveauthentication no`,
`permitrootlogin no`, `pubkeyauthentication yes`, `maxauthtries 3`. If
`passwordauthentication yes` shows, cloud-init's file is winning. Make the
hardening file sort first, then validate before reloading:
```bash
sudo mv /etc/ssh/sshd_config.d/99-officos.conf /etc/ssh/sshd_config.d/01-officos.conf
sudo sshd -t && sudo systemctl reload ssh
sudo sshd -T | grep -i '^passwordauthentication'                     # now: no
```
Firewall. Look first; don't disable it:
```bash
sudo ufw status verbose
```
SSH has to be allowed only from the LAN and from the tunnel's Docker
bridges. Add these if missing:
```bash
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp comment 'SSH from the LAN'
sudo ufw allow from 172.16.0.0/12 to any port 22 proto tcp comment 'SSH via the Cloudflare tunnel'
```
Remove a world-open rule (`22/tcp ALLOW Anywhere` or `OpenSSH ALLOW
Anywhere`) **only after step 5 works**:
```bash
sudo ufw status numbered
sudo ufw delete <number>
```
If UFW is inactive, enable it only after adding the two allow rules above,
from a session you keep open: `sudo ufw default deny incoming && sudo ufw
enable`.

**Router:** no port forwarding is needed. Make sure port 22 is **not**
forwarded to `192.168.1.115`. From a phone on mobile data,
`nc -vz 196.191.95.113 22` should time out.

Note: Docker-published ports (8000–8008, 5433-style dev ports) bypass UFW,
because Docker writes its own iptables rules. That's a separate finding
(PROJECT_STATE R8) and isn't changed here.

### 3. Operator: create the Cloudflare Access application (dashboard)

Cloudflare dashboard → **Zero Trust** → Access → Applications → **Add an
application** → **Self-hosted**.
- Application domain: `ssh.arada.click`. Session duration: 24 hours.
- Policy: **Allow**, Include: *Emails* → your own address (and anyone else
  who needs SSH). Nothing broader.
- Login method: One-time PIN (email code) is enough to start.
- Optional: under *Browser rendering* choose **SSH** to also get an
  in-browser terminal.

### 4. Publish the DNS record (after steps 2 and 3)

On the server, using the existing origin certificate:
```bash
cloudflared tunnel route dns 30a80298-fa2a-4c8a-9c86-63fdad9cb85e ssh.arada.click
```
This creates `ssh.arada.click CNAME 30a80298-fa2a-4c8a-9c86-63fdad9cb85e.cfargotunnel.com`
(proxied).

### 5. Client and tests

On each computer you SSH from (cloudflared must be installed; on this dev
machine it's `/home/prophet/bin/cloudflared`), add to `~/.ssh/config`:
```
Host ssh.arada.click
    User cosmic
    IdentityFile ~/.ssh/id_ed25519
    ProxyCommand cloudflared access ssh --hostname %h
```
Pin the host key, so the first connection can't be spoofed:
```bash
echo "ssh.arada.click $(ssh-keygen -F 192.168.1.115 | grep -m1 ed25519 | cut -d' ' -f2-3)" >> ~/.ssh/known_hosts
```
Then connect: `ssh cosmic@ssh.arada.click`. The first time, a browser window
opens for the Access login.

Tests:
```bash
dig +short ssh.arada.click                     # Cloudflare IPs (proxied CNAME)
ssh -v cosmic@ssh.arada.click true 2>&1 | grep -E "Host key|Authenticated"   # fingerprint SHA256:KlYJk3l+...wbn0
cloudflared access ssh --hostname ssh.arada.click --url localhost:2222 &   # optional local forward
ssh -p 2222 cosmic@localhost true
```
On the server:
```bash
ss -tlnp | grep ':22 '
sudo ufw status verbose
docker compose -f deploy/docker-compose.prod.yml logs --since 10m cloudflared | grep -iE 'ssh|error'
sudo journalctl -u ssh --since -10m | grep -E 'Accepted|Failed|Invalid'
```

## Troubleshooting

| Symptom | Check |
|---|---|
| `websocket: bad handshake` / 403 | Access policy doesn't include your email, or the session expired. Run `cloudflared access login https://ssh.arada.click`. |
| Hangs, then times out | `docker compose ... logs cloudflared`: an `ssh://172.17.0.1:22` dial error means UFW is blocking the Docker bridge. Add the step 2 rule. |
| `Permission denied (publickey)` | The key isn't in `~cosmic/.ssh/authorized_keys`, or the wrong `IdentityFile`. |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | Stop. Compare with `SHA256:KlYJk3l+8I/7xzvQdu8OyW6O1WRzKIgoOjL3HEvwbn0` before trusting anything. |
| `ssh.arada.click` doesn't resolve | Step 4 not done, or DNS propagation; `dig @dane.ns.cloudflare.com ssh.arada.click`. |

## Rollback

- **Disable the hostname now:** delete the `ssh.arada.click` DNS record in
  the Cloudflare dashboard. The tunnel route goes inert immediately.
- **Remove the tunnel route:** on the server, in
  `~/apps/igame/deploy/cloudflared`, restore the backup:
  `cp -p config.yml.bak-20261001T121645Z config.yml`, then
  `docker compose -f ../docker-compose.prod.yml restart cloudflared` (a few
  seconds of downtime for every hostname; do it when no real player is in an
  open round). Remove the matching block from `config.yml.example` in this
  repo.
- **sshd:** `sudo cp -a /root/ssh-backup-<stamp>/sshd_config.d/. /etc/ssh/sshd_config.d/ && sudo sshd -t && sudo systemctl reload ssh`.
- **UFW:** `sudo ufw status numbered`, then `sudo ufw delete <n>` for any
  rule added in step 2.
- **Access app:** delete it in Zero Trust → Access → Applications.
