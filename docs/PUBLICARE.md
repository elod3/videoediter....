# Publicarea pe conturile clienților

vedit poate urca clipul gata pe **YouTube, Instagram, Facebook și TikTok**, pe conturile fiecărui client.
Agentul pregătește postarea (text, hashtaguri, copertă, oră); **publică doar când îi ceri tu**, după ce ai
văzut exact ce urcă și unde.

## Cum ține clienții separați

- Fiecare client are conturile lui într-un **seif criptat** (`~/.config/vedit/vault`), câte un fișier pe client.
- Fiecare proiect e **legat de un singur client** (`vedit-accounts link`). Din proiectul ăla se poate posta
  doar pe conturile clientului ăluia. Agentul nu poate schimba legătura; o schimbi doar tu, din terminal.
- Un cont de pe o platformă nu poate fi la doi clienți.
- La publicare totul se verifică din nou: dacă proiectul a trecut între timp la alt client, publicarea e refuzată.
- Joburile din site **nu pot publica niciodată**: acolo tool-ul nici nu există.
- Fiecare publicare se scrie în jurnal: `vedit-accounts journal`.

## O singură dată: aplicațiile agenției

Fiecare platformă cere o „aplicație” a ta, prin care se conectează conturile clienților. Callback-ul e la fel
peste tot: **`http://localhost:8765/callback/`**.

### Google (YouTube)
1. [console.cloud.google.com](https://console.cloud.google.com) → proiect nou → **APIs & Services → Library →
   YouTube Data API v3 → Enable**.
2. **OAuth consent screen**: External; adaugă la *Test users* adresele Google ale clienților cât timp aplicația
   e în test.
3. **Credentials → Create credentials → OAuth client ID → Desktop app**. Copiază client ID și secret.
4. `vedit-accounts app google` și le lipești.
5. **Important:** până treci de [auditul YouTube API](https://support.google.com/youtube/contact/yt_api_form),
   video-urile urcate rămân **private**. După audit ies publice normal.

### Meta (Instagram + Facebook)
1. [developers.facebook.com](https://developers.facebook.com) → **Create app → Business**.
2. Adaugă **Facebook Login for Business** și **Instagram** (API cu Facebook Login).
3. La *Valid OAuth Redirect URIs*: `http://localhost:8765/callback/`.
4. Copiază App ID și App secret: `vedit-accounts app meta`.
5. Contul de Instagram al clientului trebuie să fie **Business sau Creator, legat de pagina lui de Facebook**.
6. Cât aplicația e în *Development*, merge doar pentru conturile cu rol în aplicație (îi adaugi pe clienți ca
   testeri). Pentru mulți clienți: **App Review** pentru permisiunile `instagram_content_publish`,
   `pages_manage_posts`, `pages_read_engagement`, `pages_show_list`, `business_management`.

### TikTok
1. [developers.tiktok.com](https://developers.tiktok.com) → **Manage apps → Connect an app**.
2. Adaugă **Login Kit** (platforma *Desktop*, redirect `http://localhost:8765/callback/`) și **Content Posting
   API** cu **Direct Post**.
3. Copiază client key și secret: `vedit-accounts app tiktok`.
4. **Până la auditul TikTok**, postările ies **private** și merg pentru cel mult 5 conturi pe zi. Auditul se
   cere din portal (Products → Content Posting API → Direct Post).

## Prima pornire

```bash
cd ~/videoediter && source .venv/bin/activate
pip install -e '.[publish]'
vedit-accounts init          # alegi parola de recuperare: o frază lungă, scrisă undeva în afara laptopului
```

## Un client nou

```bash
vedit-accounts client add service-rares --name "Service Rareș"
vedit-accounts connect service-rares youtube      # se deschide browserul; clientul se loghează (sau tu, cu acordul lui)
vedit-accounts connect service-rares meta         # alegi pagina lui; Instagramul legat de pagină vine automat
vedit-accounts connect service-rares tiktok
vedit-accounts link proiect-rares-oct service-rares
vedit-accounts list
```

## Postarea

În folderul vedit, pornești Claude Code cu publicarea permisă:

```bash
VEDIT_ALLOW_PUBLISH=1 claude
```

Apoi îi spui, de exemplu: „pregătește postarea pentru Reels și TikTok cu clipul de azi”. Agentul face pachetele
(`post_prepare`), ți le arată, iar când spui „publică”, le urcă (`post_publish`). Claude Code îți cere și el
voie înainte de fiecare publicare; nu trece `post_publish` la „allow always”.

Sau direct din terminal, fără agent:

```bash
vedit-accounts posts proiect-rares-oct            # pachetele pregătite
vedit-accounts publish proiect-rares-oct 1015-ab12cd
```

## Backup pe server (dacă formatezi laptopul)

Seiful e criptat, așa că poate sta pe server: fără parola de recuperare nu se poate citi nimic.

```bash
vedit-accounts backup --remote root@109.123.247.92:/root/vedit-vault --ssh-key ~/.ssh/lhr_key --save
vedit-accounts backup         # data viitoare, fără argumente
```

După formatare: instalezi vedit, apoi

```bash
vedit-accounts restore --remote root@109.123.247.92:/root/vedit-vault --ssh-key ~/.ssh/lhr_key
# îți cere parola de recuperare și ai înapoi toți clienții și conturile, fără să le mai ceri nimic
```

Cheia SSH (`~/.ssh/lhr_key`) trebuie și ea păstrată în afara laptopului, altfel nu mai intri pe server.

## Ce se poate și ce nu, pe platforme

| | YouTube | Instagram | Facebook | TikTok |
|---|---|---|---|---|
| ce urcă | video + Shorts | Reels (și Trial Reels) | Reels pe pagină | video |
| copertă | thumbnail (PNG/JPG) | cadru din clip | automat | cadru din clip |
| programare | da | nu (publică la ora aleasă) | da, max 75 de zile | nu |
| limită zilnică | cotă API (~100 de urcări/zi) | 100 de postări / 24 h | 30 de Reels / 24 h | 6 cereri/min, 5 conturi/zi până la audit |
| până la audit | doar privat | doar conturile cu rol în aplicație | la fel | doar privat |
