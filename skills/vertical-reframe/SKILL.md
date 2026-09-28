---
name: vertical-reframe
description: Reîncadrează un video orizontal (16:9) pentru vertical (9:16), pătrat sau 4:5, ținând subiectul în cadru, cu punch-in-uri pentru dinamism. Folosește după ce tăieturile sunt făcute și formatul e setat pe 9:16, 1:1 sau 4:5.
---

# Vertical reframe

Crop-ul 9:16 dintr-un 16:9 păstrează doar ~32% din lățime. Dacă subiectul nu e pe centru, îl pierzi.
`auto_reframe` rezolvă asta local (detecție de fețe YuNet, fără vision LLM): pune crop-ul pe fețe,
împarte clipurile exact unde subiectul se mută sau se schimbă scena și, când mai multe persoane nu încap
în cadru (podcast), **urmărește vorbitorul activ** (mișcarea gurii corelată cu audio).

## Pași

1. Ordinea: tăieturi finale → `timeline_format("9:16")` → **`auto_reframe`** → `captions_add`.
   (Împărțirea clipurilor nu strică captions, dar rulează reframe înainte ca să fie curat.)
2. Alege `punch_in`:
   | Conținut | punch_in |
   |---|---|
   | talking-head cu multe jump-cut-uri | 0.15 (alternează 1.0 / 1.15) |
   | podcast, interviu, tutorial calm | 0 |
   | sursă sub 1080p | 0 (pixelează) |
3. Citește raportul. Fiecare rând: `id [src_t0-src_t1] cx cy fețe=N [FLAG]`.
   - fără flag → gata, nu mai verifica nimic.
   - `vorbitor S0` / `vorbitor S1` → încadrat automat pe cine vorbește (S0 = cel mai din stânga). Gata.
     Comutările sub 1s („da”, „exact”) sunt ignorate intenționat — nu le „repara”.
   - `NO_FACE` (b-roll, ecran, produs) → `frames_look(asset, start=t0, end=t1, cols=3, rows=1)`, estimează unde e
     subiectul (0..1 din lățime) și `reframe("<id>", cx=...)`.
   - `WIDE` (2+ persoane care nu încap, vorbitorul nu a putut fi determinat — ex. fără audio, fețe din profil)
     → încadrat pe fața cea mai mare. Uită-te cu `frames_look` pe interval și `reframe` pe persoana potrivită.
4. Dacă raportul spune „Majoritatea marcate” (ex. panel cu 3-4 oameni, screen recording) →
   `timeline_format("9:16", fill="pad")` în loc de crop, și nu mai face reframe.
5. `cy` e calculat automat (fața puțin deasupra centrului). Ajustează manual doar dacă captions acoperă fața.

## Verificare

`render(preview=true)` → `frames_look(asset="render:preview")` → fața e în cadru în fiecare celulă și nu e
acoperită de captions? Dacă nu, `reframe` pe clipurile respective și re-randezi preview.

## Reframe manual (fallback)

`reframe(clip_ids, cx, cy, zoom)` setează încadrarea direct. Folosește-l doar pentru clipurile marcate
sau când `auto_reframe` returnează eroare (OpenCV lipsă).
