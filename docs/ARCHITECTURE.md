# Arhitectura SaaS

## Ideea centrală

**Timeline-ul JSON e produsul.** AI-ul și omul editează aceeași structură:
agentul prin tool-uri, utilizatorul prin UI (drag, trim). Randarea e mereu deterministă.
Asta te diferențiază de „generează un video și speră”: rezultatul e editabil, reproductibil și ieftin de iterat.

```
┌──────── Browser (web/, React) ────────┐
│ upload · chat cu agentul · progres    │
│ live (SSE) · player · timeline · undo │
└───────────────┬───────────────────────┘
                │ REST + Server-Sent Events
┌───────────────▼───────────────────────┐
│ vedit-server (FastAPI, vedit/api/)    │
│ proiecte pe disc · joburi în SQLite   │
│ worker: 1 job activ / proiect         │
└───────────────┬───────────────────────┘
                │ Runner (interfață comună)
   ┌────────────┼──────────────┬─────────────────────┐
   ▼            ▼              ▼                     ▼
Claude Code   Scripted     LLM (API compatibil    Hermes/OpenClaw
(`claude -p`, (fără AI,    OpenAI: OpenRouter,    (opțional)
 abonament)    demo/teste)  Ollama, vLLM...)
   │                           │
   └──MCP──► vedit-mcp         └──JSON pe linii──► toolhost (proces per job)
                 │                                     │
                 └──────► ffmpeg · whisper · YuNet · pyannote ◄──┘
```

### Runner-e

| `VEDIT_RUNNER` | Clasă | Creier | Izolarea tool-urilor | Pentru |
|---|---|---|---|---|
| `claude-code` | `ClaudeCodeRunner` | Claude Code CLI (`claude -p`) | server MCP per job, `--restricted` | test local, pe abonament |
| `llm` | `LLMRunner` (`vedit/api/llm_runner.py`) | orice `/chat/completions` cu tool calling | `vedit.api.toolhost` per job, lacăt în mediul procesului | producție pe VPS, modele ieftine |
| `scripted` | `ScriptedRunner` | fără AI, cuvinte-cheie | în proces (nu are agent) | teste, demo, fallback |
| `auto` (implicit) | | Claude Code dacă e instalat, altfel scripted | | |

`LLMRunner` în detaliu: promptul de sistem = `SYSTEM` + `SECURITY_POLICY` + skill-urile `video-editor-core` și
`edit-brief` + lista celorlalte (citite cu pseudo-tool-ul `skill_read`). Tool-urile vin din registrul MCP (fără
parametrul `project`, pe care îl injectează runner-ul) și rulează într-o gazdă separată per job, pentru că garda
citește lacătul și bugetele din mediul procesului. `image_view` (doar cu `VEDIT_LLM_VISION=1`) acceptă numai PNG/JPG
din proiect. Istoricul se salvează per sesiune în `.agent/<proiect>/`, cu rezultatele vechi scurtate în loturi
(prefix stabil pentru cache-ul de prompt al furnizorului).

### Unde rulează ce

| Etapă | Unde | Agent |
|---|---|---|
| **Acum (test)** | totul pe laptopul tău (Arch): `vedit-server` + browser pe localhost | Claude Code pe abonament |
| **Beta cu câțiva clienți** | VPS cu GPU (whisper/pyannote) + `VEDIT_API_TOKEN` | `VEDIT_RUNNER=llm`: model ieftin prin OpenRouter sau Ollama local |
| **Scalare** | API separat de workeri, coadă Redis, stocare S3/R2, Postgres | același runner, mai mulți workeri |

Nu ai nevoie de „bridge” între browser și Claude Code: API-ul pornește agentul ca proces local.
Dacă vrei site-ul pe VPS dar agentul pe laptop, worker-ul se poate muta pe laptop (citește joburi din API)
— dar fișierele video trebuie atunci sincronizate, deci pentru test e mai simplu totul local.

### Adaugi un agent nou (Hermes, OpenClaw)

Implementezi `run(project, prompt, emit, cancel, session, allow_generation) -> (mesaj_final, session_id)` (vezi `vedit/api/runners.py`):
pornești agentul cu serverul MCP `vedit-mcp` + folderul `skills/`, și transformi ce face în evenimente
`emit("tool", {...})`, `emit("tool_result", {...})`, `emit("text", {...})`. Restul (site, coadă, progres) rămâne neschimbat.

## Fluxul unui job

1. Utilizatorul urcă clipurile (API le salvează în proiect) și scrie cererea în chat → `job` în coadă.
2. Worker-ul pornește runner-ul (Claude Code acum, Hermes/OpenClaw mai târziu) cu cererea clientului; agentul urmează skill-urile `edit-brief` și `video-editor-core`.
3. Agentul: spec → analiză → tăieturi → reframe → captions → preview → QA → final.
4. Progres live prin Server-Sent Events (fiecare apel de tool = un eveniment: „tai pauzele…”, „generez subtitrări…”).
5. Render-ul apare în player; timeline-ul stă în proiect (pe disc acum, S3/Postgres la scalare).
6. **Iterație**: „mai scurt / altă muzică” → același proiect, agentul face 1-3 operații + re-render. Ieftin, rapid.

## Agenți: pornește cu UNUL

Un singur agent + skills bune bate 5 agenți prost coordonați. Adaugă roluri doar când măsori că ajută:

| Rol | Când îl adaugi | Model |
|---|---|---|
| Editor (executor) | de la început | model rapid/ieftin — face apeluri de tool |
| Director (brief → spec, alegere highlights) | când calitatea deciziilor creative e problema | model puternic, 1 apel |
| Critic QA (vision pe `frames_look(render:final)`) | când apar greșeli vizuale (subiect tăiat, text peste față) | model cu vision |

## Costuri (ordine de mărime, per 10 min de sursă)

- Transcriere: gratis local (faster-whisper pe GPU) sau câțiva cenți prin API.
- LLM: transcriptul compact ≈ 1.5k cuvinte ≈ 3-4k tokeni; un job complet ≈ 20-60k tokeni în total.
- Render: CPU, 1-3 min pentru 60s 1080p cu `preset medium`. Folosește preview 540p pentru iterații.

Prețul pe credit trebuie să acopere asta de 3-5x.

## Cum faci skill-urile „foarte precise”: evals

Skill-urile nu se scriu o dată, se **calibrează**:

1. Strânge 20-50 de clipuri reale (vlog, podcast, UGC, tutorial) + brief-uri reale.
2. Pentru fiecare, definește ce e corect: câte umpluturi trebuie scoase, durata țintă, hook-ul bun.
3. Rulează agentul pe tot setul după fiecare modificare de skill. Măsoară:
   - `qa_check.ok` rată de trecere
   - tăieturi în mijlocul cuvintelor (compară capetele clipurilor cu transcriptul)
   - % umpluturi rămase, durata vs țintă
   - tokeni și timp per minut de video
4. Când o metrică scade, schimbi UN prag/regulă în skill, re-rulezi. Asta e tot secretul.

## Roadmap toolkit

- ✅ `auto_reframe`: detecție de fețe YuNet → `cx/cy` per segment, split la mișcare/scenă, punch-in alternat.
- ✅ vorbitor activ: mișcarea gurii (repere YuNet) × vorbire în audio, histerezis → `auto_reframe` urmărește vorbitorul.
- ✅ diarizare audio (pyannote community-1): etichete în transcript, `cut_speaker`, culori per vorbitor în captions,
  reframe cu granițe exacte; vorbitor audio → față prin vot pe mișcarea gurii.
  În SaaS: rulează pe worker GPU (~1-2 min / oră de audio) sau pyannoteAI API; rezultatul intră în cache.
- **v0.2** editare text în captions (nume proprii corectate), brand kit (font, culori, logo).
- ✅ clip de referință: profil măsurat (ritm, hook, format, culoare, audio) + `style_compare` ca buclă de verificare.
- ✅ color grading: potrivire cu referința (transfer statistic LAB → LUT 3D `.cube`, aplicat cu `lut3d`),
  preseturi și reglaje, per sursă (camere diferite ajung la același look).
- ✅ pista V2 (B-roll full / PiP, aliniere pe beat), detecția beat-ului (numpy: flux mel + autocorelație +
  programare dinamică), `beat_montage` cu tăieturi pe beat.
- ✅ B-roll din afară: stock Pexels; generare AI prin fal.ai (queue API) sau Replicate (predictions), cu limită pe proiect.
- **următorul** tranziții (xfade) pe tăieturile de pe beat, speed ramp, efecte sonore (whoosh pe B-roll), downbeat sigur.
- **v0.3** b-roll: căutare stock (Pexels API) + generativ (modele video prin fal.ai/Replicate) inserat pe keyword-uri din transcript.
- **v0.3** tranziții, zoom animat (Ken Burns), sound effects pe tăieturi.
- **v0.4** render distribuit (un worker per short), GPU encoding (NVENC).
