---
name: audio-mix
description: Mixaj audio - muzică de fundal, ducking sub voce, volum per clip, loudness pe platformă. Folosește când clientul dă o melodie, cere muzică, sau audio-ul sună inegal.
---

# Audio mix

## Ținte de loudness (setate automat la render: -14 LUFS)

- TikTok / Reels / Shorts / YouTube: -14 LUFS (implicit)
- Podcast: -16 LUFS

## Muzică

- `music_set(asset, volume_db, duck=true)`:
  | Situație | volume_db | duck |
  |---|---|---|
  | vorbire peste muzică | -20 … -16 | true |
  | montaj fără voce (b-roll, travel) | -6 … 0 | false |
  | vorbire foarte încet în sursă | -24 | true |
- Muzica se repetă automat și are fade-out 1.5s la final.

## Volum per clip

`media_analyze` pe fiecare asset. Loudnorm-ul final egalizează media, dar diferențele DINTRE clipuri rămân.
Dacă două surse diferă cu > 4 LUFS, compensează: `clip_volume("c3,c4", +<diferența>)` pe clipurile din sursa mai încetă.
Nu depăși +12 dB (zgomotul de fond crește și el).

## Verificare

`qa_check` raportează loudness și true peak. true_peak > -0.5 dB = problemă.
