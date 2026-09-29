# vedit — toolkit de editare video pentru agenți AI

Motorul din spatele unui SaaS de tip „dai clipurile, AI-ul editează”.
Două piese:

1. **Toolkit (`vedit/`)** — server MCP cu 43 de tool-uri. Agentul modifică un *timeline declarativ*;
   randarea ffmpeg e deterministă. Merge cu Hermes Agent, Claude, sau orice agent cu MCP.
2. **Skills (`skills/`)** — 10 fișiere `SKILL.md` (format agentskills.io, compatibil Hermes) care îi spun
   agentului *exact* cum să editeze: ordinea pașilor, praguri numerice, reguli de decizie, condiția de „gata”.

3. **Site + API (`web/`, `vedit/api/`, decizia de design în `web/DESIGN.md`)** — editor web (upload, chat cu agentul, progres live, player, timeline
   editabil, export) peste un API FastAPI cu coadă de joburi. Agentul e interschimbabil (Claude Code acum, Hermes/OpenClaw mai târziu).

Vezi [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) pentru arhitectura completă a SaaS-ului.

## Instalare (Arch)

```bash
sudo pacman -S ffmpeg python
python -m venv .venv && source .venv/bin/activate
pip install -e '.[whisper,reframe,diarize,dev]'
export HF_TOKEN=hf_...        # pentru diarize: acceptă termenii pe hf.co/pyannote/speaker-diarization-community-1
pytest -q                     # 32 de teste, inclusiv randare, reframe, vorbitor activ și diarizare
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
| `VEDIT_RUNNER` | `auto` (implicit: Claude Code dacă e instalat), `claude-code`, `scripted` (fără AI, demo) |
| `VEDIT_CLAUDE_MODEL` | model pentru Claude Code (implicit cel din setările tale) |
| `VEDIT_HOME` | unde stau proiectele (implicit `./vedit_projects`) |
| `VEDIT_API_TOKEN` | parolă pentru API când îl pui pe un VPS |

Dezvoltare frontend cu hot reload: `vedit-server` într-un terminal, `cd web && npm run dev` în altul (http://localhost:5173).

> Abonamentul Claude e pentru uzul tău personal — perfect pentru test. Pentru clienți reali schimbi runner-ul
> (Hermes / OpenClaw cu un model ieftin, sau API); site-ul și toolkit-ul rămân identice.

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
| Control | `timeline_view`, `undo` |
| Output | `render` (preview 540p / final), `qa_check` |

## Ce înțelege agentul, fără vrăjeală

| | Da | Încă nu |
|---|---|---|
| **Audio** | transcript pe cuvânt, cine vorbește, pauze, volum (LUFS), BPM și beat-uri | downbeat sigur (e doar estimat), muzică vs vorbire, sunete (râs, aplauze) |
| **Imagine** | fețe și încadrare, tăieturi de scenă, cadre negre, culoare (LAB), contact sheet la cerere | descrierea automată a fiecărui shot, text pe ecran (OCR), mișcare / tremur |
| **Montaj** | tăieturi, ordine, format + reframe, subtitrări, text, muzică cu ducking, loudness, color grading, B-roll pe V2 (full / PiP), montaj pe beat, tranziții, zoom animat, curățare audio | speed ramp, stabilizare, efecte sonore, keyframe-uri arbitrare |
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
