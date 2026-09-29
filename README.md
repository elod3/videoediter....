# vedit — toolkit de editare video pentru agenți AI

Motorul din spatele unui SaaS de tip „dai clipurile, AI-ul editează”.
Două piese:

1. **Toolkit (`vedit/`)** — server MCP cu 50 de tool-uri. Agentul modifică un *timeline declarativ*;
   randarea ffmpeg e deterministă. Merge cu Hermes Agent, Claude, sau orice agent cu MCP.
2. **Skills (`skills/`)** — 10 fișiere `SKILL.md` (format agentskills.io, compatibil Hermes) care îi spun
   agentului *exact* cum să editeze: ordinea pașilor, praguri numerice, reguli de decizie, condiția de „gata”.

3. **Site + API (`web/`, `vedit/api/`, decizia de design în `web/DESIGN.md`)** — editor web (upload, chat cu agentul, progres live, player, timeline
   editabil, export) peste un API FastAPI cu coadă de joburi. Agentul e interschimbabil (Claude Code acum, Hermes/OpenClaw mai târziu).

Vezi [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) pentru arhitectura completă a SaaS-ului
și [`docs/DEPLOY.md`](docs/DEPLOY.md) pentru punerea pe un VPS (Docker + Caddy + HTTPS, backup, update-uri).
Comenzi scurte: `make help`.

## Instalare (Arch)

```bash
sudo pacman -S ffmpeg python
python -m venv .venv && source .venv/bin/activate
pip install -e '.[whisper,reframe,diarize,dev]'
export HF_TOKEN=hf_...        # pentru diarize: acceptă termenii pe hf.co/pyannote/speaker-diarization-community-1
pytest -q                     # 76 de teste, inclusiv randare, reframe, vorbitor activ, diarizare, brand și livrare
```

## Varianta 1: testezi toolkit-ul direct în Claude Code (fără site)

Repo-ul are deja `.mcp.json` (serverul vedit) și `.claude/skills` (skill-urile), deci Claude Code le încarcă singur:

```bash
cd videoediter && claude
> editează ~/Videos/vlog.mp4 pentru TikTok: taie pauzele, 9:16, subtitrări
```

## Varianta 2: site-ul complet, local (Claude Code pe abonamentul tău ca agent)

```bash
pip install -e '.[whisper,reframe,server,dev]'
cd web && npm install && npm run build && cd ..
vedit-server                       # http://127.0.0.1:8000
```

Browser → API (FastAPI) → worker → `claude -p` (headless) → tool-urile vedit prin MCP.
Agentul are voie DOAR la tool-urile `mcp__vedit__*`, skill-uri și citirea imaginilor din proiecte — fără Bash, fără scriere de fișiere.
Cererile următoare pe același proiect („mai scurt”, „altă muzică”) continuă aceeași conversație (`--resume`).

| Variabilă | Ce face |
|---|---|
| `VEDIT_RUNNER` | `auto` (implicit: Claude Code dacă e instalat), `claude-code`, `llm` (orice API compatibil OpenAI, vezi mai jos), `scripted` (fără AI, demo) |
| `VEDIT_CLAUDE_MODEL` | model pentru Claude Code (implicit cel din setările tale) |
| `VEDIT_HOME` | unde stau proiectele (implicit `./vedit_projects`) |
| `VEDIT_API_TOKEN` | parolă pentru API când îl pui pe un VPS |

Dezvoltare frontend cu hot reload: `vedit-server` într-un terminal, `cd web && npm run dev` în altul (http://localhost:5173).

> Abonamentul Claude e pentru uzul tău personal — perfect pentru test. Pentru clienți reali schimbi runner-ul
> (`VEDIT_RUNNER=llm` cu un model ieftin, vezi mai jos); site-ul și toolkit-ul rămân identice.

## Agent de producție (orice API compatibil OpenAI)

Pentru clienți reali, fără abonament Claude: `VEDIT_RUNNER=llm` vorbește cu orice endpoint
`/chat/completions` cu tool calling (OpenRouter, Ollama, vLLM, Groq, Together...). Doar biblioteca standard, fără SDK.

```bash
# OpenRouter
export VEDIT_RUNNER=llm
export VEDIT_LLM_BASE_URL=https://openrouter.ai/api/v1
export VEDIT_LLM_API_KEY=sk-or-...
export VEDIT_LLM_MODEL=qwen/qwen3-coder          # orice model cu tool calling
export VEDIT_LLM_HEADERS='{"HTTP-Referer": "https://site-ul-tau.ro", "X-Title": "vedit"}'
vedit-server

# Ollama pe același VPS (fără cheie)
export VEDIT_RUNNER=llm
export VEDIT_LLM_BASE_URL=http://localhost:11434/v1
export VEDIT_LLM_MODEL=qwen2.5:14b
vedit-server
```

| Variabilă | Ce face |
|---|---|
| `VEDIT_LLM_BASE_URL` | baza API-ului (se adaugă `/chat/completions`) |
| `VEDIT_LLM_API_KEY` | cheia (opțională pentru Ollama / vLLM local) |
| `VEDIT_LLM_MODEL` | modelul; trebuie să știe tool calling |
| `VEDIT_LLM_MAX_TURNS` | pași per job (implicit 40) |
| `VEDIT_LLM_VISION` | `1` = modelul vede imagini (`image_view` pe contact sheet-uri din proiect); `0` = doar tool-uri numerice |
| `VEDIT_LLM_HEADERS` | headere extra, JSON |
| `VEDIT_LLM_TIMEOUT` | timeout per cerere HTTP (implicit 180 s); 429/5xx se reîncearcă de 3 ori, cu pauză crescătoare |

Cum e izolat: fiecare job pornește propria gazdă de tool-uri (`python -m vedit.api.toolhost`) cu
`VEDIT_PROJECT_LOCK=<proiect>` în mediul ei, bugete proprii și fără cheile de generare dacă clientul nu a bifat-o.
Modelul nu vede parametrul `project` (îl pune runner-ul) și nu are decât tool-urile vedit, `skill_read` și,
opțional, `image_view`. Skill-urile `video-editor-core` și `edit-brief` sunt în promptul de sistem, restul se citesc la nevoie.
Conversația se salvează în `$VEDIT_HOME/.agent/<proiect>/llm_session_<id>.json`, deci „mai scurt” continuă
de unde a rămas (rezultatele vechi de tool se scurtează, ca să nu crească factura).

## Conturi, credite și plăți

Cu `VEDIT_AUTH=on` serverul devine multi-client: fiecare utilizator are cont, își vede doar proiectele lui
(pe disc stau ca `u{id}-{nume}`, iar agentul e blocat pe exact acel folder prin `VEDIT_PROJECT_LOCK`),
iar exportul final consumă credite. **1 credit = 1 minut început de video final** (preview-urile sunt gratuite).
Fără credite, jobul de agent și randarea finală răspund `402`. Implicit (`off`) totul merge ca înainte, cu `VEDIT_API_TOKEN`.

| Variabilă | Ce face |
|---|---|
| `VEDIT_AUTH` | `on` = conturi + credite + plăți; `off` (implicit) = un singur utilizator |
| `VEDIT_FREE_CREDITS` | credite la înregistrare (implicit 3) |
| `VEDIT_SESSION_DAYS` | cât ține o sesiune (implicit 30) |
| `VEDIT_PACKS` | pachetele de vânzare, JSON: `[{"id":"starter","credits":30,"price_id":"price_…","label":"30 de minute"}]` |
| `STRIPE_SECRET_KEY` | cheia secretă Stripe (`sk_…`) |
| `STRIPE_WEBHOOK_SECRET` | secretul endpoint-ului de webhook (`whsec_…`) |
| `VEDIT_PUBLIC_URL` | adresa site-ului (întoarcerea din Stripe Checkout; `https://` => cookie `Secure`) |

| Endpoint | Ce face |
|---|---|
| `POST /api/auth/register` `{email, password}` | cont nou (parolă ≥ 8 caractere) → `{token, user}` + cookie HttpOnly |
| `POST /api/auth/login` `{email, password}` | → `{token, user}` + cookie; max 10 greșeli / 10 min per IP + email |
| `POST /api/auth/logout` | închide sesiunea |
| `GET /api/me`, `GET /api/me/ledger` | email + credite; istoricul creditelor |
| `GET /api/billing/packs` | pachetele (fără `price_id`) |
| `POST /api/billing/checkout` `{pack}` | → `{url}` spre Stripe Checkout |
| `POST /api/billing/webhook` | pentru Stripe (`checkout.session.completed`), verificat prin semnătură, idempotent |

Autentificarea: `Authorization: Bearer <token>`, cookie-ul `vedit_session` sau `?token=` (pentru `<video>` și SSE).
În Stripe adaugi un webhook spre `https://site/api/billing/webhook` cu evenimentele `checkout.session.completed`
și `checkout.session.async_payment_succeeded`.

## Conectare la Hermes Agent

```bash
cp -r skills/* ~/.hermes/skills/          # skill-urile
cat hermes/config.example.yaml            # adaugă blocul mcp_servers în ~/.hermes/config.yaml
```

## Test rapid din terminal (fără agent)

```bash
vedit asset_add project=demo path=~/Videos/vlog.mp4
vedit cut_silences project=demo asset=a0
vedit timeline_format project=demo fmt=9:16
vedit transcript_get project=demo asset=a0
vedit captions_add project=demo asset=a0 style=karaoke
vedit render project=demo preview=false
vedit qa_check project=demo
```

## Tool-uri

| Grup | Tool-uri |
|---|---|
| Ingest | `asset_add`, `asset_list` |
| Analiză | `media_analyze` (liniști, LUFS, scene, cadre negre), `transcript_get` (id pe cuvânt), `diarize` (pyannote: cine vorbește când, din audio), `speakers_detect` (același lucru din imagine), `frames_look` (contact sheet) |
| Tăieturi | `cut_silences`, `cut_words`, `keep_words`, `cut_speaker` (scoate / păstrează un vorbitor), `range_remove` |
| Clipuri | `clip_add`, `clip_remove`, `clip_move`, `clip_trim`, `clip_volume` |
| Imagine | `timeline_format` (9:16, 16:9, 1:1, 4:5), `auto_reframe` (încadrare pe fețe + split la mișcare/scenă + urmărirea vorbitorului), `reframe` (manual) |
| Text/audio | `captions_add` (bold_center, karaoke, classic_bottom, culori per vorbitor), `text_add`, `music_set` (loop + ducking) |
| Referință & culoare | `asset_role` (marchează referința), `reference_analyze` (ritm, hook, culoare, audio, format — măsurate), `color_match` (preia culoarea referinței printr-un LUT 3D), `color_grade` (preseturi + reglaje), `color_reset`, `style_compare` (montajul tău vs referința, cu sfaturi) |
| B-roll & muzică | `broll_add` (pista V2, tot ecranul sau PiP, cu aliniere pe beat), `broll_remove`, `beats_detect` (BPM + beat-uri), `beat_montage` (tăieturi pe beat), `broll_stock` (footage real, Pexels), `broll_generate` (video AI prin fal.ai / Replicate, plătit, doar la cerere) |
| Finisaj | `transition_set` (18 tranziții xfade, audio crossfade), `zoom_animate` (push-in / Ken Burns cu easing), `audio_check` (SNR, clipping, măsurate), `audio_clean` (reducere de zgomot calibrată pe zgomotul măsurat, poartă, de-esser, compresor) |
| Brand kit | `brand_logo` (watermark PNG/JPG cu transparență, colț, mărime, opacitate), `brand_captions` (culori #RRGGBB + fontul clientului .ttf/.otf pentru subtitrări și titluri), `brand_intro_outro` (lipite automat la randare), `brand_clear` |
| Control | `timeline_view`, `undo` |
| Output | `render` (preview 540p / final), `qa_check`, `export_preset` (tiktok, reels, shorts, youtube, instagram_feed, linkedin, x: format + loudness + render + QA), `captions_export` (.srt / .vtt), `thumbnail_export` (cel mai clar cadru, cu fețe, + titlu) |

## Ce înțelege agentul, fără vrăjeală

| | Da | Încă nu |
|---|---|---|
| **Audio** | transcript pe cuvânt, cine vorbește, pauze, volum (LUFS), BPM și beat-uri | downbeat sigur (e doar estimat), muzică vs vorbire, sunete (râs, aplauze) |
| **Imagine** | fețe și încadrare, tăieturi de scenă, cadre negre, culoare (LAB), contact sheet la cerere | descrierea automată a fiecărui shot, text pe ecran (OCR), mișcare / tremur |
| **Montaj** | tăieturi, ordine, format + reframe, subtitrări, text, muzică cu ducking, loudness, color grading, B-roll pe V2 (full / PiP), montaj pe beat, tranziții, zoom animat, curățare audio | speed ramp, stabilizare, efecte sonore, keyframe-uri arbitrare |
| **Brand & livrare** | logo, culori și font pe subtitrări, intro/outro, preseturi pe platformă, SRT/VTT, thumbnail | template-uri animate (lower thirds), mai multe logo-uri, thumbnail cu decupaj de persoană |
| **Referință** | ritm, hook, format, culoare, volum — măsurate și comparate cu montajul | stilul subtitrărilor și B-roll-ul se judecă vizual de agent, nu se măsoară |

Pe scurt: editează real un talking-head, podcast sau UGC pentru social media (cu B-roll peste vorbire și în stilul
unui clip dat) și montaje fără vorbire tăiate pe beat. Tranzițiile, speed ramp-ul și efectele sonore urmează.

### Chei pentru B-roll din afară (opționale)

| Variabilă | Pentru |
|---|---|
| `PEXELS_API_KEY` | footage stock gratuit (pexels.com/api) |
| `FAL_KEY` + `VEDIT_FAL_MODEL` | generare video pe fal.ai (ID-ul modelului din pagina lui, ex. un model text-to-video) |
| `REPLICATE_API_TOKEN` + `VEDIT_REPLICATE_MODEL` | generare pe Replicate (`owner/nume`) |
| `VEDIT_GEN_EXTRA` | parametri specifici modelului, JSON (ex. `{"negative_prompt": "text, logo"}`) |
| `VEDIT_GEN_LIMIT` | câte generări pe proiect (implicit 3), ca să nu arzi bani din greșeală |

### Brand și livrare, pe scurt

- **Straturi** (de jos în sus): V1 + grading → B-roll (V2) → logo → subtitrări și titluri. Logo-ul nu acoperă niciodată textul.
- **Intro/outro** nu intră în timeline: se lipesc la randare. Tăieturile, subtitrările, B-roll-ul și beat-urile rămân
  în timpul montajului; la randare totul se decalează cu durata intro-ului. Logo-ul și muzica stau doar pe montaj.
- Fișierele de brand se copiază în `<proiect>/brand/` (nume cu hash, deci `undo` revine exact); randarea refuză
  logo/font din afara proiectului, chiar dacă timeline-ul vine din API.
- API: `GET /api/projects/{name}/captions.srt|vtt`, `GET /api/projects/{name}/thumbnail.png` (`vedit/api/routes_export.py`).

## Evaluări: cum știi dacă agentul editează bine

`vedit-eval evals/ --runner claude-code` rulează agentul pe clipurile tale reale și verifică obiectiv fiecare caz
(format, durată, subtitrări, QA, tăieturi în mijlocul cuvintelor, ce tool-uri a folosit sau nu). Raportul iese în
`eval-report/report.md`. Detalii și un caz exemplu în `evals/`.

## Securitate: prompt injection și abuz

Agentul citește conținut pe care nu îl controlezi: ce se spune în video, nume de fișiere, metadate stock, cererile
clienților. Limitele importante sunt impuse în cod (`vedit/guard.py`), deci țin chiar dacă modelul e păcălit:

| Risc | Blocaj |
|---|---|
| Agentul atinge proiectele altor clienți | `VEDIT_PROJECT_LOCK`: serverul MCP al jobului refuză orice alt proiect |
| Citește sau importă fișiere din afara proiectului (`/etc/…`, alt client, symlink) | căile se rezolvă și trebuie să fie în proiect; Claude Code rulează `--restricted`, cu citire doar din proiect |
| Cheltuie bani pe generare AI | bifă de consimțământ per cerere în UI; fără ea tool-ul refuză, iar cheile nici nu ajung la agent |
| Buclă infinită / consum de CPU | buget de apeluri, randări și descărcări per job; timeout pe job (`VEDIT_JOB_TIMEOUT`) |
| Text din video care dă ordine („ignoră instrucțiunile…”) | conținutul extern vine împachetat ca DATE, tiparele de injecție sunt detectate și apar ca avertisment în UI |
| Rularea de comenzi | fără Bash, fără scriere de fișiere, fără web (`--disallowedTools`, `--restricted`, `dontAsk`) |

Testele din `tests/test_guard.py` sunt atacuri concrete care trebuie să eșueze.

## De ce e eficient

- **Editare prin text**: agentul șterge `w120-w134` din transcript, nu ghicește secunde → tăieturi precise.
- **Stare pe server**: timeline-ul stă pe disc; agentul trimite operații mici și primește ~1 rând/clip.
- **Reframe fără LLM**: detecție de fețe locală (YuNet, inclus) → crop 9:16 corect, fără tokeni de vision.
  În podcast-uri urmărește vorbitorul activ (gura se mișcă + se aude vorbire), cu histerezis de 1s.
- **Diarizare legată de tot**: după `diarize`, transcriptul arată `A:`/`B:`, poți tăia după vorbitor,
  subtitrările au culori per vorbitor, iar reframe-ul taie cadrul exact când începe replica (vorbitor audio → față prin vot).
- **Un singur „ochi”**: `frames_look` = 12 cadre într-o imagine → un apel vision în loc de 12.
- **Zero ffmpeg halucinat**: LLM-ul decide, codul execută. Erorile vin ca text clar, iar operațiile eșuate nu strică starea.
- **Undo + cache**: fiecare modificare e reversibilă; analizele și transcrierea se calculează o singură dată.
- **QA obiectiv**: durată, rezoluție, loudness (-14 LUFS), cadre negre, liniști — agentul nu declară „gata” fără `ok: true`.
