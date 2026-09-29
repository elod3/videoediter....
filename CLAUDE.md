# CLAUDE.md — ghid pentru agenții AI care lucrează PE acest repo

vedit = SaaS de editare video cu agent AI. Clientul urcă clipuri și scrie ce vrea; un agent editează
un **timeline declarativ** prin tool-uri MCP; ffmpeg randează determinist. Proprietar: fondator solo,
dezvoltă pe Arch Linux, deploy pe un VPS ieftin (vezi `docs/DEPLOY.md`).

## Harta codului

| Unde | Ce face |
|---|---|
| `vedit/timeline.py` | modelul Timeline (pydantic): clipuri V1, B-roll V2, captions, text, muzică, format, culoare. **Sursa de adevăr.** |
| `vedit/project.py` | `Project` = asset-uri + cache de analize + timeline + istoric (undo). Toate operațiile de editare |
| `vedit/render.py` | Timeline → O SINGURĂ comandă ffmpeg (`filter_complex`). Fără LLM, determinist |
| `vedit/ff.py`, `probe.py` | găsirea/rularea ffmpeg și ffprobe (`VEDIT_FFMPEG`, `VEDIT_FFPROBE`) |
| `vedit/analyze.py` | liniști, tăieturi de scenă, loudness, cadre negre, contact sheet |
| `vedit/transcribe.py` | faster-whisper, cuvinte cu id (`w12`) pentru tăieturi precise |
| `vedit/captions.py` | transcript → subtitrări `.ass` (libass) |
| `vedit/faces.py`, `reframe.py`, `speaker.py` | YuNet (model inclus în `vedit/models/`), încadrare 9:16, vorbitor activ |
| `vedit/diarize.py` | pyannote („cine vorbește când”), opțional (`HF_TOKEN`) |
| `vedit/style.py` | profilul unui clip de referință, color grading prin LUT 3D |
| `vedit/beats.py`, `audiofx.py` | BPM/beat-uri (numpy), curățarea vocii |
| `vedit/sources.py` | B-roll din afară: Pexels, fal.ai, Replicate |
| `vedit/edit_ops.py` | mixin pentru `Project`: viteză, freeze, efecte, grafice, sfx, multicam, fundal, capitole, corecturi de text |
| `vedit/graphics.py` | motion graphics → ASS animat (lower third, title card, counter, listă, callout, cerc...) |
| `vedit/sfx.py` | efecte sonore sintetizate (numpy), cache în `VEDIT_HOME/.sfx` |
| `vedit/multicam.py` | sincronizarea camerelor după sunet, planul de schimbare a cadrelor |
| `vedit/segment.py` | decuparea persoanei (MODNet ONNX prin OpenCV): fundal înlocuit, text în spatele persoanei |
| `vedit/guard.py` | **securitate**: lacăt pe proiect/fișiere, consimțământ generare, bugete, conținut extern ca DATE |
| `vedit/mcp_server.py` | serverul MCP (`vedit-mcp`): tool-uri subțiri peste `Project`, toate prin decoratorul `@tool` |
| `vedit/cli.py` | `vedit <tool> k=v` pentru debug |
| `vedit/api/app.py` | FastAPI (`vedit-server`): proiecte, upload, timeline, joburi, SSE, servește `web/dist` |
| `vedit/api/jobs.py`, `db.py` | worker în proces (1 job activ / proiect, 2 thread-uri), SQLite pentru joburi + evenimente |
| `vedit/api/runners.py` | runner-ele agentului: `ClaudeCodeRunner` (`claude -p`), `ScriptedRunner` (fără AI) |
| `web/` | React 19 + Vite + TS. `npm run dev` (proxy `/api` → :8000), `npm run build` → `web/dist`. Estetica: `web/DESIGN.md` |
| `skills/*/SKILL.md` | instrucțiunile agentului-editor (format agentskills.io) |
| `tests/` | pytest; `synth.py`/`drums.py` generează media de test |
| `Dockerfile`, `docker-compose.yml`, `deploy/` | imagine + Caddy (HTTPS, SSE, upload mare) + unitate systemd |

## Convenții (nu le încălca)

1. **Timeline declarativ + randare deterministă.** Agentul (și UI-ul) modifică doar structura `Timeline`;
   niciodată nu generează comenzi ffmpeg. Tot ffmpeg-ul se construiește în `render.py` / `analyze.py`.
2. **Orice mutație trece prin `Project.edit()`** (context manager): snapshot pentru undo, rollback la excepție,
   salvare atomică, **ripple** (subtitrările, graficele, B-roll-ul, sfx-urile și capitolele urmează tăieturile;
   vezi `timeline.ripple`). Nu scrie direct în `p.s.timeline` în afara lui `with p.edit():`.
   Timpii de pe timeline țin cont de viteză și freeze: folosește `Clip.duration`, `Clip.src_at`, `Clip.tl_at`,
   nu `src_out - src_in`.
3. **Tool-urile MCP sunt subțiri:** validare + apel în `Project` + text compact. Logica stă în `project.py`
   și modulele de domeniu. Orice tool nou: decoratorul `@tool` (buget + lacăt pe proiect), căile primite
   de la agent trec prin `guard.check_path`, conținutul extern (transcript, nume de fișiere, metadate)
   iese prin `guard.untrusted(...)`. Erorile se întorc ca text clar, pe care agentul îl poate corecta.
4. **Textul pentru utilizatori e în română** (mesaje de eroare, UI, rapoarte, docs, commit-uri).
   Identificatorii din cod rămân în engleză.
5. **Testele randează media reală cu ffmpeg** (clipuri sintetice din `tests/conftest.py`, `synth.py`).
   Nu mock-ui ffmpeg-ul; verifică durata/rezoluția/loudness-ul fișierului rezultat. Testele care au nevoie de
   rețea sau de extras opționale fac `pytest.skip` / `importorskip`.
6. **Invarianții de securitate din `vedit/guard.py` nu se slăbesc niciodată:**
   - `VEDIT_PROJECT_LOCK`: un job atinge doar proiectul lui (`check_project` în fiecare tool);
   - căile se rezolvă (symlink, `..`) și trebuie să fie în proiect (`check_path`);
   - generarea AI plătită cere `VEDIT_ALLOW_GENERATION=1`, pus DOAR de bifa utilizatorului; cheile
     `FAL_KEY`/`REPLICATE_API_TOKEN` nu ajung la agent fără ea (`runners.py`);
   - bugete per job (`VEDIT_MAX_TOOL_CALLS`, `VEDIT_MAX_RENDERS`, `VEDIT_MAX_STOCK_DOWNLOADS`), timeout de job;
   - conținutul extern e împachetat ca DATE, cu detecție de tipare de injecție;
   - Claude Code rulează fără Bash/Write/Edit/Web (`--disallowedTools`, `--restricted`, `dontAsk`).
   `tests/test_guard.py` conține atacuri concrete: trebuie să rămână verzi. Dacă o funcționalitate nouă
   pare să ceară relaxarea unei limite, oprește-te și întreabă.
7. Operațiile eșuate nu au voie să strice starea (vezi rollback-ul din `edit()`); analizele scumpe se cache-uiesc
   în `proiect/cache/` prin `Project._cache`.

## Skill-uri și runner-e

- `skills/<nume>/SKILL.md` sunt instrucțiunile pentru agentul care EDITEAZĂ video (nu pentru tine ca programator).
  `.claude/skills` e symlink spre `skills/`, deci Claude Code deschis în repo le vede direct, împreună cu
  `.mcp.json` (serverul `vedit`).
- `ClaudeCodeRunner` creează per proiect `VEDIT_HOME/.agent/<proiect>/` cu `.claude/skills → VEDIT_SKILLS_DIR`
  și un `mcp.json` cu lacătul pe proiect, apoi rulează `claude -p` cu promptul de sistem din `runners.py`
  (începe cu `edit-brief` + `video-editor-core`). Sesiunea se reia cu `--resume` pentru iterații.
- Un runner nou (API/LLM, Hermes) implementează `run(project, prompt, emit, cancel, session, allow_generation)`
  și emite `status` / `tool` / `tool_result` / `text` / `security`. Site-ul nu se schimbă.
- Abonamentul Claude (runner-ul `claude-code`) e doar pentru testul personal al proprietarului; clienții
  reali vor folosi un runner prin API.

## Comenzi

```bash
python -m venv .venv && source .venv/bin/activate
make install                  # pip install -e '.[whisper,reframe,server,dev]' + npm ci în web/
make test                     # pytest -q (are nevoie de ffmpeg cu libass + libx264 în PATH)
pytest tests/test_guard.py -q # doar testele de securitate
make dev                      # vedit-server :8000 + Vite :5173
make build-web && vedit-server   # site-ul construit, pe http://127.0.0.1:8000
VEDIT_RUNNER=scripted vedit-server   # fără AI
make docker-build && make docker-up  # ca în producție (cere .env, vezi .env.example)
make lint                     # ruff (informativ; există câteva avertismente vechi în tests/)
```

CI (`.github/workflows/ci.yml`): pytest pe Python 3.11 și 3.12 cu ffmpeg din apt, build-ul frontend-ului,
build-ul imaginii Docker + verificare `/api/health`.

## Variabile de mediu

Toate sunt documentate în `.env.example`. Dacă adaugi una în cod, adaug-o și acolo (în grupul potrivit)
și, dacă e relevantă la deploy, în `docs/DEPLOY.md`.
