---
name: audiogram
description: Podcast audio, voice note, emisiune radio sau înregistrare fără imagine transformată în video pentru social media - fundal (copertă / poză / culoare de brand), unda sunetului animată, subtitrări mari, titlu. Folosește când clientul urcă DOAR audio (mp3, m4a, wav) și vrea să-l posteze, sau zice „audiogram”, „undă”, „waveform”, „podcast fără video”, „clip din podcastul audio”.
---

# Audiogram

## Pași

1. Audio lung (peste 3 min)? Întâi alege fragmentul: `highlights_find(asset, n=5, min_len=20, max_len=60)`, apoi
   `transcript_get` pe zona aleasă. Un audiogram pe social are 20-60 s. Dai fragmentul direct: `audiogram(...,
   start=<început>, end=<sfârșit>)` (secunde din audio; pornește și termină pe fraze întregi). Pentru mai multe
   fragmente, câte un proiect / randare pe rând. Episodul întreg (YouTube): fără start/end.
2. `audiogram(audio, image=<coperta / poza gazdei>, color=<culoarea brandului>, style, fmt)`:
   - **fmt:** `9:16` TikTok / Reels / Shorts, `1:1` feed Instagram / LinkedIn, `16:9` YouTube.
   - **style:** `wave` (undă plină, elegant), `bars` (egalizator, energic), `line` (minimal).
   - **wave_color:** culoarea de accent a brandului (`brand_kit`), contrast mare pe fundal.
   - Cu fragment, răspunsul spune id-ul NOU al sunetului (ex. `a0f0`): pe el faci captions.
3. `captions_add(asset=<id-ul din răspuns>, style="bold_center")` (9:16 / 1:1) sau `classic_bottom` (16:9). Pe audiogram,
   subtitrările SUNT conținutul: mari, cu cuvinte-cheie (`captions_emphasis`).
4. Titlu: `graphic_add` `title_card` sau `lower_third` cu numele podcastului / episodului în primele 3 s.
5. `render` → `frames_look`: unda nu trebuie să se suprapună cu subtitrările; dacă se suprapun, mută unda
   cu `audiogram(..., position="top")` sau folosește stilul de subtitrare `classic_bottom`.
