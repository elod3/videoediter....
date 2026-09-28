---
name: talking-head-cleanup
description: Curăță un video cu o persoană care vorbește la cameră (vlog, podcast, tutorial, UGC) - scoate pauze, "ăăă/hmm", bâlbe, repetări și duble. Folosește când clientul cere "taie pauzele", "fă-l mai dinamic", "jump cuts", "curăță clipul".
---

# Talking-head cleanup

## Pași

1. `media_analyze(asset)` → uită-te la `silence_total` și `loudness.lufs`.
   - Dacă `lufs < -35`: vocea e foarte încet → folosește `noise_db = lufs - 10` la tăiere.
2. `cut_silences(asset, min_silence=…, padding=0.1)` — alege `min_silence` după ritm:
   | Ritm cerut          | min_silence | padding |
   |---------------------|-------------|---------|
   | TikTok / Reels agresiv | 0.30     | 0.06    |
   | YouTube normal      | 0.50        | 0.10    |
   | Podcast / interviu  | 0.90        | 0.15    |
3. `transcript_get(asset)` și caută, în ordinea asta:
   - **Duble / retake-uri**: aceeași frază (sau aproape) spusă de 2+ ori → păstrează ULTIMA variantă completă,
     șterge-le pe cele dinainte. Semnal: fraze care încep la fel la câteva secunde distanță.
   - **Fraze abandonate**: frază neterminată urmată de restart ("deci am vrut... deci azi vă arăt").
   - **Umpluturi**: ăă, ăăă, îîî, hmm, uh, um, gen (ca umplutură), deci (la început de frază repetat), știi, practic (tic).
     Șterge-le DOAR dacă sunt izolate — nu tăia "deci" care leagă logic două idei.
   - **Repetări de cuvânt**: "și și", "că că".
4. Trimite TOATE ștergerile într-un singur apel: `cut_words(asset, "w12-w15,w40,w88-w102")`.
5. Verifică: `transcript_get` pe 1-2 zone tăiate NU arată timeline-ul — citește `timeline_view` și confirmă
   că niciun clip < 0.3s nu a rămas izolat (clipurile foarte scurte arată ca glitch → șterge-le cu `clip_remove`).

## Nu face

- Nu scoate respirațiile de dinaintea unei fraze emoționale — ritmul contează.
- Nu tăia mai mult de 40% din durată fără să fie cerut; raportează dacă se întâmplă.
