---
name: multicam
description: Montaj cu mai multe camere care au filmat același moment (podcast cu 2-3 camere, interviu, eveniment, tutorial cu cameră + ecran). Sincronizează după sunet, schimbă camera pe cine vorbește, split-screen. Folosește când clientul urcă 2+ clipuri video ale aceluiași moment sau zice „multicam”, „am filmat din mai multe unghiuri”, „podcast cu două camere”.
---

# Multicam

## Recunoaște situația
Mai multe asset-uri video cu durate apropiate, filmate în paralel (același sunet de cameră, aceleași persoane din
unghiuri diferite). Confirmă cu `frames_look` pe fiecare: cine se vede, cadru larg (wide) sau apropiat.
Notează: `a0 = wide (ambii)`, `a1 = close Ana`, `a2 = close Mihai`.

## Pașii
1. **Sincronizare:** `multicam_sync(angles="a0,a1,a2", reference=<camera cu cel mai bun sunet>)`.
   - Referința dă sunetul și timpul montajului.
   - Dacă răspunde „sincronizare nesigură”, camerele nu au sunet comun: spune-i clientului, nu ghici.
2. **Tăieturi pe referință**, ca la un singur clip: `media_analyze`, `diarize` (2+ vorbitori), `transcript_get`,
   `cut_silences`, `cut_words`. Toate tăieturile se fac pe referință; camerele o urmează automat.
3. **Cine e pe ce cameră:** `diarize` dă S0, S1. Din `frames_look` pe camere și din transcript (cine se prezintă, cine
   pune întrebări) faci legătura: `S0=a1,S1=a2`. Nu ghici: dacă nu e clar, folosește `speakers_detect` pe camera wide.
4. **Schimbarea camerelor:**
   - **Dialog:** `multicam_auto(mode="speaker", mapping="S0=a1,S1=a2", wide="a0", min_shot=1.5, wide_every=20)`.
   - **Monolog din mai multe unghiuri:** `multicam_auto(mode="rotate", mapping="x=a0,y=a1", every=4)`.
   - **Momente speciale (manual):**
     - `multicam_angle(start, end, "a0")` pentru o reacție sau o glumă, pe wide;
     - `split_screen(start, end, "a1,a2", "stack")` pentru o dezbatere rapidă în 9:16.
5. `timeline_format` → `auto_reframe`: încadrează fiecare unghi pe fața lui.
6. Continuă cu restul workflow-ului (captions, grafice, sunet).

## Gust de editor
- **Cadrul minim 1.5 s** (1.2 s la ritm alert, 2.5 s la interviu calm). Sub asta, pare nervos.
- **Taie pe camera celui care vorbește, dar nu la fiecare „da” scurt.** min_shot le absoarbe.
- **Wide la întrebări lungi, râsete, suprapuneri, și măcar o dată la 20-30 s** ca privitorul să știe unde e.
- **9:16 cu două persoane:** `split_screen` stack arată ambele reacții; folosește-l pe schimburi rapide, nu pe tot clipul.
- **Nu schimba camera în mijlocul unui cuvânt.** Modul rotate taie pe finaluri de cuvânt; la manual, ia timpii din transcript.

## Verificare
`render(preview)` → `frames_look(asset="render:preview")`. Verifică:
- fiecare cadru arată persoana care vorbește;
- nu apar cadre negre (o cameră pornită prea târziu dă eroare clară la `multicam_angle`);
- `qa_check` trece.
