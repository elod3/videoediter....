---
name: faceless-video
description: Clipuri fără persoană pe ecran, cu voce generată din text (voice-over AI local) peste poze, clipuri stock sau B-roll - explicații, top-uri, liste, povești, reclame cu produse, „faceless YouTube / TikTok”. Folosește când clientul dă un script / un text / o idee și imagini (sau cere stock), zice „voice-over”, „citește textul”, „fără să apar eu”, „faceless”, „narațiune”.
---

# Faceless video (voice-over + imagini)

## Pașii
1. **Scriptul:**
   - Dacă clientul dă textul, îl folosești aproape neschimbat: corectezi doar ce se pronunță greșit.
   - Dacă dă doar o idee, scrii tu:
     - hook în prima frază (max 10 cuvinte);
     - fraze scurte;
     - 130-160 de cuvinte pentru ~60 s.
   - Pronunție: cifrele importante se scriu în litere („trei trucuri”); fără emoji sau abrevieri.
2. `voiceover(script, lang)`. Limba este cea a clientului sau a publicului lui (ro, en, hu, de, es, fr, it). Durata vine
   din voce: nu forța viteza peste 1.15.
3. **Imaginile:**
   - Pozele și clipurile clientului sau `broll_stock` (câte un query concret pe idee).
   - `generate` doar cu bifă (vezi `broll-and-beats`).
   - Ordinea lor = ordinea în care scriptul vorbește despre ele.
4. `timeline_format` (9:16 pentru TikTok / Reels / Shorts), apoi `visuals_fill(assets, per=2.5-4)`:
   - pozele primesc Ken Burns;
   - clipurile sunt tăiate la `per` secunde.

   După, ajustează cu `clip_trim` / `clip_move` ca imaginea să se schimbe pe ideea potrivită (timpii din
   `transcript_get(asset=<voice-over>)`).
5. **Subtitrări:** `captions_add(asset=<voice-over>, style="bold_center")`, apoi `captions_emphasis("auto")`.
   Opțional: `graphic_add` (list pentru top-uri, counter pentru cifre) și `sfx_auto`.
6. **Muzică** (dacă există piesa), cu `music_set`: se coboară singură sub voce. Fără muzică, `sfx_auto` ajunge.
7. `render(preview)` → `frames_look` → `render(final)` → `qa_check`.

## Reguli
- Imaginea se schimbă la 2-4 s (TikTok) sau 4-7 s (YouTube). Același cadru mai mult de 7 s = plictis.
- Vocea e generată local; spune-i clientului că e voce AI.
- Dacă clientul a urcat propria înregistrare (audio), folosește-o: `narration_set(asset)` în loc de `voiceover`,
  apoi `media_analyze` + `cut_silences` nu se aplică pe narațiune (e pe A3); taie-o înainte, în alt proiect,
  sau cere-i o înregistrare curată. Subtitrările: `captions_add(asset=<înregistrarea>)`.
- Nu inventa informații în script care nu vin de la client, dacă e un subiect factual (cifre, prețuri, promisiuni).
