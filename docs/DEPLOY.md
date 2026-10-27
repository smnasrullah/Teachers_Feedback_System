# Deploying the Teacher Feedback System

This guide puts the system on **one Linux server** with your own domain name and automatic
HTTPS. You do not need to know Docker or Linux well: follow the steps in order and copy the
commands exactly.

Every command block says where to type it:

- **On my Windows PC**: in PowerShell on your own computer.
- **On the server**: in the SSH window connected to the server.

Replace anything in `<angle brackets>` with your own value (without the brackets).

> **The app holds real student data.** Read the go-live checklist at the end before you tell
> anyone the address.

---

## What you need first

| Item | Notes |
|---|---|
| A VPS (virtual server) | Ubuntu **24.04 LTS**, 2 CPU cores, 4 GB RAM, 40 GB disk is enough for one university. Any provider (DigitalOcean, Hetzner, Linode, Vultr, a university data centre…). |
| A domain or sub-domain | For example `feedback.your-university.edu`. You must be able to change its DNS records. |
| An SMTP e-mail account | For round reminders and result notices (sign-in never uses e-mail). Your university's mail server or a mail service. |
| A safe place for keys | A password manager or an encrypted USB stick, **not** on the server. |
| An authenticator app | Google or Microsoft Authenticator on your phone, for the first Admin account. |

---

## 1. Create an SSH key (once)

**On my Windows PC:**

```powershell
ssh-keygen -t ed25519
```

Press Enter three times (default file, then a passphrase if you want one). Show the public key:

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```

Copy that line; the VPS provider asks for it in the next step.

## 2. Create the server

In your provider's control panel:

1. Create a new server ("droplet", "instance", "VPS") with **Ubuntu 24.04 LTS**.
2. Add the SSH public key from step 1.
3. Note the server's **public IPv4 address**, for example `203.0.113.10`.

## 3. Point your domain at the server

In your domain's DNS settings add an **A record**:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `feedback` (or `@` for the bare domain) | `<server IPv4 address>` | 300 |

Check it (it can take a few minutes up to an hour):

**On my Windows PC:**

```powershell
Resolve-DnsName <your domain>
```

It must show the server's IP address before step 9, or HTTPS cannot be set up.

## 4. Log in and create a normal user

**On my Windows PC:**

```powershell
ssh root@<server IP>
```

**On the server** (as root), create the user `tfs` and let it use your SSH key:

```bash
adduser --gecos "" tfs
usermod -aG sudo tfs
rsync --archive --chown=tfs:tfs ~/.ssh /home/tfs
```

Choose a strong password for `tfs` when asked. Then switch off password and root logins over SSH:

```bash
sed -i -e 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' \
       -e 's/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart ssh
exit
```

From now on log in as `tfs`. **On my Windows PC:**

```powershell
ssh tfs@<server IP>
```

## 5. Firewall: allow only SSH, HTTP and HTTPS

**On the server:**

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ufw unattended-upgrades
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

`unattended-upgrades` installs Ubuntu security updates automatically.

> Docker can open ports past ufw. That is why only the `caddy` container publishes ports (80
> and 443); the database and Redis publish none and sit on an internal Docker network.

## 6. Install Docker

**On the server** (Docker's official repository):

```bash
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker tfs
exit
```

Log in again (**On my Windows PC:** `ssh tfs@<server IP>`) and check:

```bash
docker compose version
```

## 7. Get the code

**On the server:**

```bash
cd ~
git clone <your repository URL> Teachers_Feedback_System
cd Teachers_Feedback_System
```

For a private GitHub repository, add a read-only **deploy key** first (repository → Settings
→ Deploy keys) or use a fine-grained access token with read-only access.

## 8. Create the `.env` file with your own keys

**On the server:**

```bash
cp .env.production.example .env
chmod 600 .env
```

Make four random values. Run each line and keep the output for the next step:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"                         # DJANGO_SECRET_KEY
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"  # FIELD_ENCRYPTION_KEYS
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                         # BLIND_INDEX_KEY
python3 -c "import secrets; print(secrets.token_hex(24))"                             # POSTGRES_PASSWORD
```

Open the file and fill in every `change-me` plus `DOMAIN`, `ACME_EMAIL` and the `EMAIL_*` lines:

```bash
nano .env
```

(Save with **Ctrl+O**, Enter; quit with **Ctrl+X**.) Each key must be different. The app
**refuses to start** while a secret is missing, too short, or still `change-me`.

### Back up the keys now, apart from the database

`FIELD_ENCRYPTION_KEYS` and `BLIND_INDEX_KEY` protect encrypted columns and student-ID
look-ups. **If you lose them, that data is gone for good: no backup and no developer can
bring it back.** A database backup without these keys cannot be read.

**On my Windows PC**, copy `.env` to your computer, then move it into your password manager
or an encrypted USB stick and delete the copy:

```powershell
scp tfs@<server IP>:Teachers_Feedback_System/.env "$env:USERPROFILE\Desktop\tfs-production.env"
```

Keep this copy **separate from** the database backups (different place, different access).

## 9. Start the system

**On the server** (first build takes 5–10 minutes):

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

Wait until `web` shows `healthy`. Caddy then gets the HTTPS certificate on its own.

Tip: to type less, add a short name once:

```bash
echo "alias dc='docker compose -f ~/Teachers_Feedback_System/docker-compose.prod.yml'" >> ~/.bashrc
source ~/.bashrc
```

The rest of this guide writes the full command, but `dc` works the same (`dc ps`, `dc logs web`).

## 10. Create the first Admin

**On the server:**

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py create_admin
```

Enter a contact e-mail and a strong password. Note the **username** it prints. Open
`https://<your domain>` and sign in; you are asked to set up the authenticator app right
away. Save the recovery codes it shows.

## 11. Load the question bank and the people registry

**On the server**, load the standard questions:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py load_questions docs/QUESTION_BANK.md
```

Then in the browser, as Admin: **Manage → ID registry → Import** and upload the student and
teacher lists (Excel or CSV), then generate activation codes. `docs/ADMIN_GUIDE.md` explains
handing them out.

## 12. Test HTTPS

**On my Windows PC:**

```powershell
curl.exe -I http://<your domain>
curl.exe -s https://<your domain>/healthz
```

The first must answer `308` (redirect to HTTPS); the second must print `{"status": "ok"}`. In
the browser, the padlock must show a valid certificate. You can also run the free test at
`https://www.ssllabs.com/ssltest/` (expect grade A).

---

## Daily operation

### See the logs

**On the server:**

```bash
docker compose -f docker-compose.prod.yml logs --tail 100 web
docker compose -f docker-compose.prod.yml logs --tail 100 worker
docker compose -f docker-compose.prod.yml logs -f            # live; Ctrl+C to stop
```

The app never logs passwords, codes or feedback text, and there is no web access log (request
times could be matched against submissions).

### Back up the database every night

**On the server**, make the backup folder and a first backup:

```bash
mkdir -p ~/tfs-backups
~/Teachers_Feedback_System/scripts/backup.sh
ls -lh ~/tfs-backups
```

Then schedule it daily at 02:15 (`crontab -e`, choose nano, add this line at the bottom):

```cron
15 2 * * * $HOME/Teachers_Feedback_System/scripts/backup.sh >> $HOME/tfs-backups/backup.log 2>&1
```

It keeps the newest 14 dumps. A copy only on the same server is not a real backup: set
`BACKUP_COPY_CMD` to copy each dump elsewhere, for example with `rclone` to cloud storage:

```cron
15 2 * * * BACKUP_COPY_CMD='rclone copy "$1" offsite:tfs-backups' $HOME/Teachers_Feedback_System/scripts/backup.sh >> $HOME/tfs-backups/backup.log 2>&1
```

Or pull them to your PC now and then. **On my Windows PC:**

```powershell
scp "tfs@<server IP>:tfs-backups/*.dump" "$env:USERPROFILE\Documents\tfs-backups\"
```

Uploaded avatars and teacher photos live in the `tfs_media` Docker volume; they are not in the
dump (people can upload them again).

### Update to a new version

**On the server:**

```bash
cd ~/Teachers_Feedback_System
scripts/backup.sh
git log -1 --format=%H > ~/tfs-previous-version
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

Database changes run automatically when `web` starts.

### Roll back a bad update

**On the server:**

```bash
cd ~/Teachers_Feedback_System
git checkout "$(cat ~/tfs-previous-version)"
docker compose -f docker-compose.prod.yml up -d --build
```

If the update changed the database, also restore the backup taken just before it (next
section). Return to the latest code later with `git checkout main && git pull`.

### Restore a backup

**On the server** (stops the site for a minute, replaces **all** data):

```bash
cd ~/Teachers_Feedback_System
ls -lh ~/tfs-backups
scripts/restore.sh ~/tfs-backups/<file name>.dump
```

Type `RESTORE` when asked. `.env` must contain the **same** keys as when the backup was made.

### Test a restore (do this before go-live, then every term)

A backup you have never restored is a guess. On a **staging copy** (a second small server set
up with steps 1–9, with the same `.env` keys but its own `DOMAIN`), copy a dump over and
restore it. **On my Windows PC:**

```powershell
scp "tfs@<server IP>:tfs-backups/<file name>.dump" .
scp ".\<file name>.dump" "tfs@<staging IP>:"
```

**On the staging server:**

```bash
cd ~/Teachers_Feedback_System
scripts/restore.sh ~/<file name>.dump
```

Sign in on the staging site and check that a closed round's report opens and that the Admin
can search the ID registry (this proves the encryption and blind-index keys match).

---

## Go-live checklist

Tick every line before announcing the address:

- [ ] **Unique keys generated** on this server for `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEYS`,
      `BLIND_INDEX_KEY` and `POSTGRES_PASSWORD` (none copied from an example, a test or
      another install), and the `.env` copy is stored apart from the database backups.
- [ ] **Every Admin account has TOTP** (authenticator app) set up and its recovery codes stored.
- [ ] **`MIN_RESPONSES` is set** to the agreed value (default 5, never below 3) on
      Manage → System settings.
- [ ] **One full test round on a staging copy**: open a round, submit as test students,
      close it, check that teacher and HOD reports appear only after closing and stay hidden
      below `MIN_RESPONSES`.
- [ ] **Anonymity audit run**: run the test suite (`pytest -q`) on the release you deploy and
      confirm that no report, export or log shows who wrote which answer, and that student IDs
      appear only to the Admin and the student's own HOD.
- [ ] **Backup restore tested** on the staging copy (section above), and the nightly cron job
      writes a new file in `~/tfs-backups`.
- [ ] **Privacy notice page reviewed** by the university (what is collected, who sees what,
      how long it is kept).
- [ ] `https://<your domain>/healthz` answers `{"status": "ok"}` and `http://` redirects to
      `https://`.
