# vedit — toolkit de editare video pentru agenți AI

Motorul din spatele unui SaaS de tip „dai clipurile, AI-ul editează”.
Două piese:

1. **Toolkit (`vedit/`)** — server MCP cu 27 de tool-uri. Agentul modifică un *timeline declarativ*;
   randarea ffmpeg e deterministă. Merge cu Hermes Agent, Claude, sau orice agent cu MCP.
2. **Skills (`skills/`)** — 8 fișiere `SKILL.md` (format agentskills.io, compatibil Hermes) care îi spun
   agentului *exact* cum să editeze: ordinea pașilor, praguri numerice, reguli de decizie, condiția de „gata”.

Vezi [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) pentru arhitectura completă a SaaS-ului.

## Instalare (Arch)

```bash
sudo pacman -S ffmpeg python
python -m venv .venv && source .venv/bin/activate
pip install -e '.[whisper,reframe,diarize,dev]'
export HF_TOKEN=hf_...        # pentru diarize: acceptă termenii pe hf.co/pyannote/speaker-diarization-community-1
pytest -q                     # 32 de teste, inclusiv randare, reframe, vorbitor activ și diarizare
```

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
| Control | `timeline_view`, `undo` |
| Output | `render` (preview 540p / final), `qa_check` |

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
