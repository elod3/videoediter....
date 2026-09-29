# Deploy pe un VPS (Hetzner / orice Ubuntu)

Ghid practic, de la zero la `https://domeniul-tău.ro` cu HTTPS, backup și update-uri.
Toate comenzile sunt de copiat în terminal. Unde vezi `vedit.exemplu.ro`, pune domeniul tău.

**Pe scurt:** VPS cu 4 nuclee → Docker → `git clone` → `.env` → `docker compose up -d` → înregistrare DNS.
Caddy face singur certificatul HTTPS.

---

## 1. Ce server îți trebuie

**Nucleele de CPU contează cel mai mult.** ffmpeg (randare, analiză) folosește toate nucleele;
un preview de 60 s în 540p durează câteva secunde, un final 1080p cam 1-3 min pe 4 nuclee.
Transcrierea (whisper) și diarizarea (pyannote) merg și pe CPU, doar mai încet. GPU-ul e opțional.

| Etapă | Server | Ce duce |
|---|---|---|
| Test / demo | 2 vCPU, 4 GB RAM, 40 GB disc | tu + 1-2 prieteni, fără whisper sau cu modelul `small` |
| **Beta cu primii clienți (recomandat)** | **4 vCPU, 8 GB RAM, 80-160 GB disc** | 2 joburi în paralel (atât rulează worker-ul acum), whisper pe CPU |
| Mai mulți clienți | 8 vCPU dedicate, 16-32 GB RAM | randări mai rapide, whisper `medium` |
| Transcriere/diarizare rapidă | server cu GPU (ex. Hetzner GEX, sau GPU închiriat la oră) | doar când CPU-ul devine gâtul de sticlă |

Pe Hetzner Cloud: seria **CPX** (AMD, vCPU partajate) e cel mai bun raport preț/putere pentru început;
seria **CCX** (vCPU dedicate) când randările încep să se calce pe picioare. Alege o locație din UE
(Falkenstein / Nuremberg / Helsinki) și imaginea **Ubuntu 24.04**.

**Discul se umple repede:** fiecare proiect ține uploadurile clientului + randările. 10 clienți × 5 proiecte
× 2 GB = 100 GB. Poți adăuga oricând un *Volume* Hetzner și muta `data/` pe el.

### Cost lunar estimativ

Prețurile se schimbă; verifică pe hetzner.com înainte să comanzi. Ordine de mărime (2026, fără TVA):

| Ce | Cât |
|---|---|
| VPS 2 vCPU / 4 GB (test) | ~4-6 € |
| VPS 4 vCPU / 8 GB (beta) | ~8-16 € |
| VPS 8 vCPU dedicate / 32 GB | ~50-60 € |
| Backup: Hetzner Storage Box 1 TB | ~4 € |
| Domeniu `.ro` / `.com` | ~10-15 € / an |
| LLM prin API, per job de editare (20-60k tokeni) | câțiva cenți până la ~0,5 $ (depinde de model) |
| Generare video AI (fal.ai / Replicate), doar la cerere | 0,1-1 $ / clip generat |
| Stripe (când adaugi plăți) | comision per tranzacție, vezi stripe.com/pricing |

Regula din `docs/ARCHITECTURE.md`: prețul pe credit trebuie să acopere costul real de 3-5 ori.

---

## 2. Pregătirea serverului (o singură dată)

### 2.1. Primul login și utilizator normal

La crearea serverului în Hetzner, adaugă cheia ta SSH (de pe Arch: `cat ~/.ssh/id_ed25519.pub`;
dacă nu ai una: `ssh-keygen -t ed25519`).

```bash
ssh root@IP_SERVER

adduser deploy                      # parola ți-o cere o singură dată (pentru sudo)
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh && chmod 700 /home/deploy/.ssh
```

Oprește login-ul cu parolă și cel ca root (verifică întâi, **în alt terminal**, că `ssh deploy@IP_SERVER` merge):

```bash
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/; s/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart ssh
exit
```

De aici lucrezi ca `deploy`:

```bash
ssh deploy@IP_SERVER
sudo apt update && sudo apt upgrade -y
sudo apt install -y git ufw unattended-upgrades htop ncdu
sudo dpkg-reconfigure -plow unattended-upgrades     # update-uri de securitate automate: alege „Yes”
```

### 2.2. Firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp      # HTTP/3 (opțional)
sudo ufw enable
sudo ufw status
```

> **Atenție la Docker + ufw:** porturile publicate de Docker (`ports:` în compose) ocolesc ufw.
> De aceea `docker-compose.yml` publică DOAR 80/443 (Caddy); aplicația (8000) e vizibilă numai în rețeaua
> internă Docker. Nu adăuga `ports: - "8000:8000"` la serviciul `vedit`.
> Poți pune și firewall-ul din panoul Hetzner (Cloud → Firewalls) cu aceleași reguli, ca a doua barieră.

### 2.3. Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
exit                        # ieși și intră din nou ca să se aplice grupul
ssh deploy@IP_SERVER
docker run --rm hello-world
docker compose version
```

---

## 3. Instalarea aplicației

### 3.1. Codul

```bash
cd ~
git clone https://github.com/UTILIZATORUL_TAU/videoediter.git vedit
cd vedit
```

Repo privat? Creează un *deploy key* (GitHub → repo → Settings → Deploy keys) cu
`ssh-keygen -t ed25519 -f ~/.ssh/github_vedit` și clonează cu `git@github.com:...`.

### 3.2. Configurarea (`.env`)

```bash
cp .env.example .env
openssl rand -hex 32        # copiază rezultatul: e parola API-ului
nano .env
```

Minimul de completat:

```ini
DOMAIN=vedit.exemplu.ro
ACME_EMAIL=tu@exemplu.ro
VEDIT_API_TOKEN=<rezultatul de la openssl>
VEDIT_RUNNER=scripted
VEDIT_CPUS=4               # câte nuclee are serverul (sau mai puțin), NU mai multe
VEDIT_MEMORY=6g            # lasă ~1-2 GB pentru sistem și Caddy
INSTALL_WHISPER=1          # dacă vrei subtitrări/tăieturi pe cuvânt (imagine mai mare)
```

Toate variabilele sunt explicate în `.env.example`.

> **Important (până vin conturile):** `VEDIT_API_TOKEN` e o singură parolă comună. Oricine o are vede și
> poate șterge **toate** proiectele. Dă-o doar oamenilor în care ai încredere (beta închis).
> Clienții plătitori au nevoie de conturi separate (în lucru: `VEDIT_AUTH`, Stripe).

### 3.3. Folderul de date

Containerul rulează ca utilizatorul cu UID 1000 (pe Ubuntu, primul utilizator creat, deci `deploy`, are tot 1000).

```bash
mkdir -p data
sudo chown -R 1000:1000 data
```

### 3.4. DNS

La registrarul domeniului (sau în Cloudflare), adaugă:

| Tip | Nume | Valoare |
|---|---|---|
| A | `vedit` (sau `@` pentru domeniul gol) | IP-ul IPv4 al serverului |
| AAAA (opțional) | la fel | IP-ul IPv6 al serverului |

Verifică de pe laptop: `dig +short vedit.exemplu.ro` trebuie să dea IP-ul serverului.
**Fă asta înainte de pornire**, altfel Let's Encrypt nu poate emite certificatul.
Dacă folosești Cloudflare, lasă norișorul **gri** (DNS only) la început; proxy-ul lor limitează uploadurile la 100 MB pe planul gratuit.

### 3.5. Pornirea

```bash
docker compose up -d --build      # prima dată durează 3-10 minute (construiește imaginea)
docker compose ps                 # vedit trebuie să fie „healthy”
docker compose logs -f caddy      # aștepți „certificate obtained successfully”, apoi Ctrl+C
curl https://vedit.exemplu.ro/api/health
```

Răspuns corect: `{"ok":true,"runner":"scripted","auth":true}`. Deschide `https://vedit.exemplu.ro`
în browser; la prima cerere îți cere tokenul (cel din `.env`).

---

## 4. Operare zilnică

### Loguri

```bash
docker compose logs -f --tail=100 vedit     # aplicația (joburi, erori ffmpeg)
docker compose logs -f --tail=100 caddy     # accesări, HTTPS (tokenul din URL apare ca REDACTED)
docker stats                                 # CPU / RAM pe container, live
df -h && ncdu ~/vedit/data                   # cât disc ocupă proiectele
```

### Update la o versiune nouă

```bash
cd ~/vedit
git pull
docker compose build
docker compose up -d
docker image prune -f        # șterge imaginile vechi (altfel se umple discul)
```

Joburile care rulează în momentul repornirii se pierd (worker-ul e în proces). Fă update-ul când nu
lucrează nimeni, sau verifică întâi în UI că nu e niciun job activ.

### Backup (obligatoriu înainte de primul client)

Ce contează: `~/vedit/data/` (proiecte + `projects/vedit.db`) și `~/vedit/.env`.
Certificatele HTTPS se regenerează singure, nu trebuie salvate.

**Varianta simplă: rsync pe alt calculator / Storage Box**

```bash
# copie consistentă a bazei SQLite (în timp ce aplicația rulează)
docker compose exec -T vedit python -c "import sqlite3; s=sqlite3.connect('/data/projects/vedit.db'); d=sqlite3.connect('/data/projects/vedit.backup.db'); s.backup(d); d.close()"
rsync -az --delete ~/vedit/data/ ~/vedit/.env uXXXXX@uXXXXX.your-storagebox.de:vedit-backup/ -e 'ssh -p 23'
```

**Varianta recomandată: restic (criptat, incremental, cu istoric)**

```bash
sudo apt install -y restic
# o singură dată: cheia SSH pentru Storage Box + inițializarea depozitului
ssh-keygen -t ed25519 -f ~/.ssh/storagebox -N ''
cat ~/.ssh/storagebox.pub | ssh -p 23 uXXXXX@uXXXXX.your-storagebox.de install-ssh-key
printf 'Host storagebox\n  HostName uXXXXX.your-storagebox.de\n  User uXXXXX\n  Port 23\n  IdentityFile ~/.ssh/storagebox\n' >> ~/.ssh/config
openssl rand -hex 24 > ~/.restic-pass && chmod 600 ~/.restic-pass    # PĂSTREAZĂ și în managerul de parole
restic -r sftp:storagebox:restic-vedit -p ~/.restic-pass init
```

Scriptul de backup `~/backup-vedit.sh`:

```bash
#!/bin/sh
set -e
cd ~/vedit
docker compose exec -T vedit python -c "import sqlite3; s=sqlite3.connect('/data/projects/vedit.db'); d=sqlite3.connect('/data/projects/vedit.backup.db'); s.backup(d); d.close()"
restic -r sftp:storagebox:restic-vedit -p ~/.restic-pass backup ~/vedit/data ~/vedit/.env --exclude '*.part' --exclude 'data/cache'
restic -r sftp:storagebox:restic-vedit -p ~/.restic-pass forget --keep-daily 7 --keep-weekly 4 --keep-monthly 3 --prune
```

```bash
chmod +x ~/backup-vedit.sh
crontab -e
# adaugă linia (în fiecare noapte la 03:30):
30 3 * * * /home/deploy/backup-vedit.sh >> /home/deploy/backup.log 2>&1
```

**Testează restaurarea o dată** (un backup netestat nu e backup):

```bash
restic -r sftp:storagebox:restic-vedit -p ~/.restic-pass snapshots
restic -r sftp:storagebox:restic-vedit -p ~/.restic-pass restore latest --target /tmp/restore-test
```

Pentru restaurare după o problemă: oprești (`docker compose down`), copiezi `data/` înapoi,
redenumești `vedit.backup.db` în `vedit.db` dacă cea originală e stricată, `sudo chown -R 1000:1000 data`, pornești.

### Curățenie (discul)

Randările și uploadurile vechi ocupă cel mai mult. Vezi ce e mare cu `ncdu ~/vedit/data/projects`.
Până există o politică automată de retenție, șterge proiectele vechi din UI sau manual
(`rm -rf data/projects/NUME`, cu aplicația pornită e ok: proiectul pur și simplu dispare din listă).

### Monitorizare minimă

1. **Uptime:** cont gratuit pe UptimeRobot (sau Uptime Kuma pe alt server) care verifică
   `https://vedit.exemplu.ro/api/health` la 5 minute și îți trimite email / Telegram când pică.
2. **Disc:** alertă când trece de 80%. Truc gratuit cu healthchecks.io: creezi un check cu perioada 1 oră
   și pui în `crontab -e` o linie care îi dă „ping” DOAR cât timp discul e sub 80%. Când se umple,
   ping-urile se opresc și primești email:
   ```bash
   0 * * * * [ $(df --output=pcent / | tail -1 | tr -dc 0-9) -lt 80 ] && curl -fsS -m 10 https://hc-ping.com/UUID-UL-TAU > /dev/null
   ```
   Același trick merge și pentru backup: adaugă `&& curl -fsS https://hc-ping.com/ALT-UUID` la finalul liniei de cron a backup-ului.
3. **Resurse:** `docker stats` și `htop`. Dacă CPU-ul stă la 100% minute în șir, fie crești `VEDIT_CPUS`,
   fie treci pe un server mai mare.
4. **Sănătatea containerului:** `docker compose ps` arată `healthy`/`unhealthy` (healthcheck pe `/api/health`
   la 30 s). `restart: unless-stopped` îl repornește dacă procesul moare.

---

## 5. Ce agent (runner) folosești în producție

| Runner | Ce e | Când |
|---|---|---|
| `scripted` | pipeline fix, fără AI (taie pauze, format, reframe, subtitrări, după cuvinte-cheie) | demo public, fallback, teste; merge în Docker din prima |
| `claude-code` | `claude -p` pe **abonamentul tău** Claude | **doar pe laptopul tău, pentru tine** |
| API / LLM (`VEDIT_LLM_*`) | agent care vorbește direct cu un API de model (OpenRouter, Anthropic API etc.), plătit per token | **clienți reali** (runner-ul e în lucru) |

**De ce abonamentul Claude nu e pentru clienți:** abonamentele Pro/Max sunt pentru uz personal. Să rulezi
cererile altor oameni (clienți plătitori) prin contul tău personal încalcă termenii, îți poate bloca
contul și oricum nu scalează (limite de utilizare pe cont, o singură sesiune de login pe server).
Pentru clienți folosești **API-ul**: facturare per token, termeni comerciali, chei pe care le poți roti.
Costul intră în prețul creditelor (vezi tabelul de costuri de mai sus).

În plus, imaginea Docker nu conține binarul `claude`, deci `VEDIT_RUNNER=auto` cade automat pe `scripted`.
Până e gata runner-ul prin API, pe server rulezi `VEDIT_RUNNER=scripted`, iar agentul AI îl testezi local
(`vedit-server` pe Arch cu Claude Code, vezi README).

Orice runner ai folosi, limitele de securitate din `vedit/guard.py` (lacăt pe proiect, bugete per job,
consimțământ pentru generarea plătită) se aplică la fel.

---

## 6. Varianta fără Docker (systemd + Caddy nativ)

Util dacă vrei să vezi totul „la vedere” sau serverul e prea mic pentru Docker. Pe Ubuntu 24.04:

```bash
# pachete de sistem
sudo apt install -y python3 python3-venv ffmpeg fonts-dejavu-core git
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
# Caddy (repo-ul oficial)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

# utilizator și foldere
sudo useradd --system --create-home --home-dir /home/vedit --shell /usr/sbin/nologin vedit
sudo mkdir -p /opt/vedit /srv/vedit/projects /srv/vedit/cache
sudo chown -R vedit:vedit /srv/vedit
sudo chown deploy:deploy /opt/vedit

# cod + venv + frontend (ca deploy)
git clone https://github.com/UTILIZATORUL_TAU/videoediter.git /opt/vedit
cd /opt/vedit
python3 -m venv .venv
.venv/bin/pip install -e '.[server,reframe,whisper]'
cd web && npm ci && npm run build && cd ..

# configurare
cp .env.example .env && nano .env        # VEDIT_API_TOKEN, DOMAIN, ACME_EMAIL etc.
sudo chown deploy:vedit .env && sudo chmod 640 .env

# serviciul aplicației
sudo cp deploy/vedit.service /etc/systemd/system/vedit.service
sudo systemctl daemon-reload
sudo systemctl enable --now vedit
curl http://127.0.0.1:8000/api/health
```

Caddy nativ, cu același `deploy/Caddyfile` (upstream-ul devine `127.0.0.1:8000`):

```bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo mkdir -p /etc/systemd/system/caddy.service.d
printf '[Service]\nEnvironment=DOMAIN=vedit.exemplu.ro\nEnvironment=ACME_EMAIL=tu@exemplu.ro\nEnvironment=UPSTREAM=127.0.0.1:8000\n' \
  | sudo tee /etc/systemd/system/caddy.service.d/vedit.conf
sudo systemctl daemon-reload && sudo systemctl restart caddy
journalctl -u caddy -f        # aștepți certificatul
```

Update fără Docker:

```bash
cd /opt/vedit && git pull
.venv/bin/pip install -e '.[server,reframe,whisper]'
cd web && npm ci && npm run build && cd ..
sudo systemctl restart vedit
```

Loguri: `journalctl -u vedit -f`. Backup: la fel ca mai sus, dar cu `/srv/vedit` în loc de `~/vedit/data`
(copia SQLite: `sudo -u vedit /opt/vedit/.venv/bin/python -c "import sqlite3; ..."` cu calea `/srv/vedit/projects/vedit.db`).

---

## 7. Probleme frecvente

| Simptom | Cauză probabilă | Rezolvare |
|---|---|---|
| Caddy: `challenge failed` / fără HTTPS | DNS-ul nu arată încă spre server, sau portul 80 blocat | `dig +short DOMENIU`, `sudo ufw status`, firewall-ul Hetzner; apoi `docker compose restart caddy` |
| `vedit` nu pornește: `range of CPUs is from 0.01 to N` | `VEDIT_CPUS` mai mare decât nucleele serverului | scade `VEDIT_CPUS` în `.env`, `docker compose up -d` |
| `PermissionError: /data/projects` | `data/` nu e al UID 1000 | `sudo chown -R 1000:1000 data` |
| Upload-ul se oprește la ~100 MB | Cloudflare cu proxy (norișor portocaliu) | pune DNS only (gri) |
| Progresul live nu apare, doar la final | un proxy în față care bufferizează | fără alt proxy în fața lui Caddy; Caddyfile are deja `flush_interval -1` |
| Containerul e omorât (`OOMKilled`) | whisper/pyannote + randare pe prea puțin RAM | crește `VEDIT_MEMORY` sau serverul |
| `401 neautorizat` | token greșit în browser | șterge tokenul salvat (datele site-ului) și introdu-l din nou |
