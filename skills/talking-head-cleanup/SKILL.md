---
name: talking-head-cleanup
description: Curăță un video cu o persoană care vorbește la cameră (vlog, podcast, tutorial, UGC) - scoate pauze, "ăăă/hmm", bâlbe, repetări și duble. Folosește când clientul cere "taie pauzele", "fă-l mai dinamic", "jump cuts", "curăță clipul".
---

# Talking-head cleanup

## Pași

0. `audio_check(asset)`: dacă SNR < 35 dB, aplică presetul recomandat cu `audio_clean`. `strong` doar sub 15 dB,
   fiindcă poate tăia finalul cuvintelor; verifică pe preview. Dacă raportează clipping, spune-i clientului:
   distorsiunea nu se repară.
1. `media_analyze(asset)` → uită-te la `silence_total` și `loudness.lufs`.
   - Dacă `lufs < -35`: vocea e foarte încet → folosește `noise_db = lufs - 10` la tăiere.
2. `cut_silences(asset, min_silence=…, padding=0.1)` — alege `min_silence` după ritm:
   | Ritm cerut          | min_silence | padding |
   |---------------------|-------------|---------|
   | TikTok / Reels agresiv | 0.30     | 0.06    |
   | YouTube normal      | 0.50        | 0.10    |
   | Podcast / interviu  | 0.90        | 0.15    |
3. `clean_speech(asset)`: scoate automat „ăăă/hmm/um” izolate și repetițiile imediate („eu eu”, „și asta și asta”),
   păstrând ultima variantă. Citește raportul: dacă a scos un cuvânt util (ex. „deci” care leagă idei), `undo`
   și fă tăieturile manual. `lang="ro"` când știi limba.
4. `transcript_get(asset)` și caută ce nu prinde automat:
   - **Duble / retake-uri**: aceeași frază (sau aproape) spusă de 2+ ori → păstrează ULTIMA variantă completă,
     șterge-le pe cele dinainte. Semnal: fraze care încep la fel la câteva secunde distanță.
   - **Fraze abandonate**: frază neterminată urmată de restart ("deci am vrut... deci azi vă arăt").
   - **Ticuri verbale**: gen (ca umplutură), deci (la început de frază repetat), știi, practic (tic).
     Șterge-le DOAR dacă sunt izolate — nu tăia "deci" care leagă logic două idei.
5. Trimite TOATE ștergerile într-un singur apel: `cut_words(asset, "w12-w15,w40,w88-w102")`.
6. **Mai mulți vorbitori** (interviu, podcast): rulează `diarize(asset)` (cu `num_speakers` dacă știi câți sunt).
   Transcriptul arată apoi `A: ...` / `B: ...`. Cereri tipice:
   - „scoate întrebările moderatorului” → identifică moderatorul din transcript (cel care pune întrebări) → `cut_speaker(asset, "A")`
   - „doar răspunsurile invitatului” → `cut_speaker(asset, "B", keep=true)`
   Atenție: fără întrebare, un răspuns poate să nu mai aibă sens. Dacă răspunsul începe cu „da”/„nu”/„exact”,
   păstrează întrebarea sau pune-o ca `text_add` deasupra.
7. **Ritm (TikTok/Reels/Shorts, o singură cameră):** după `timeline_format` și `auto_reframe`, `auto_pacing(max_static=3)`
   împarte cadrele lungi pe final de cuvânt și alternează cu punch-in. YouTube: `max_static=6`, `zoom=1.1`.
8. Verifică: `transcript_get` pe 1-2 zone tăiate NU arată timeline-ul — citește `timeline_view` și confirmă
   că niciun clip < 0.3s nu a rămas izolat (clipurile foarte scurte arată ca glitch → șterge-le cu `clip_remove`).

## Nu face

- Nu scoate respirațiile de dinaintea unei fraze emoționale — ritmul contează.
- Nu tăia mai mult de 40% din durată fără să fie cerut; raportează dacă se întâmplă.
