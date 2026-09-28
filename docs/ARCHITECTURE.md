# Arhitectura SaaS

## Ideea centrală

**Timeline-ul JSON e produsul.** AI-ul și omul editează aceeași structură:
agentul prin tool-uri, utilizatorul prin UI (drag, trim). Randarea e mereu deterministă.
Asta te diferențiază de „generează un video și speră”: rezultatul e editabil, reproductibil și ieftin de iterat.

```
┌──────────── Frontend (Next.js) ────────────┐
│ upload direct în S3/R2 (presigned URL)     │
│ prompt: "fă 3 shorts pt TikTok din podcast"│
│ player preview + timeline read/write + chat│
└───────────────┬────────────────────────────┘
                │ REST / WebSocket (progres)
┌───────────────▼────────────────────────────┐
│ API (FastAPI): auth, credite, joburi       │
│ Postgres: users, projects, jobs, timeline  │
└───────────────┬────────────────────────────┘
                │ coadă (Redis + arq / Celery)
┌───────────────▼────────────────────────────┐
│ Worker de job                              │
│  Hermes Agent  ──MCP──►  vedit-mcp         │
│   + skills/*           ├─ ffmpeg (CPU)     │
│                        └─ whisper (GPU/API)│
└───────────────┬────────────────────────────┘
                ▼
        S3/R2: surse, cache, render-uri
```

## Fluxul unui job

1. Utilizatorul urcă clipurile → API creează `project` + `job` → coadă.
2. Worker-ul descarcă sursele local, pornește Hermes cu prompt-ul: brief-ul clientului + „urmează `edit-brief`, apoi `video-editor-core`”.
3. Agentul: spec → analiză → tăieturi → reframe → captions → preview → QA → final.
4. Progres pe WebSocket (fiecare apel de tool = un eveniment: „tai pauzele…”, „generez subtitrări…”).
5. Output în S3, link în UI. Timeline-ul se salvează în Postgres.
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
- **v0.2** active speaker (diarizare + mișcarea buzelor) → `auto_reframe` alege vorbitorul la segmentele WIDE.
- **v0.2** editare text în captions (nume proprii corectate), brand kit (font, culori, logo).
- **v0.3** b-roll: căutare stock (Pexels API) + generativ (modele video prin fal.ai/Replicate) inserat pe keyword-uri din transcript.
- **v0.3** tranziții, zoom animat (Ken Burns), sound effects pe tăieturi.
- **v0.4** render distribuit (un worker per short), GPU encoding (NVENC).
