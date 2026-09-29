---
name: captions-and-text
description: Alege și aplică subtitrări și text pe ecran (stil, timing, titluri, hook text). Folosește când video-ul are vorbire sau clientul cere subtitrări / text / titluri.
---

# Captions & text

## Alegerea stilului

| Platformă / conținut | style |
|---|---|
| TikTok, Reels, Shorts, UGC ads | `bold_center` (1-3 cuvinte, majuscule, sub față la ~70% din înălțime) |
| Educațional scurt, energic | `karaoke` (cuvântul curent evidențiat) |
| YouTube long-form, podcast, interviu | `classic_bottom` |

## Reguli

- `captions_add` se rulează **ultimul** din partea de tăieturi. Dacă tai după, rulează-l din nou (suprascrie).
- Verifică transcriptul pentru nume proprii / branduri greșit transcrise. Dacă sunt greșite, raportează-le în final
  (toolkit-ul nu are încă editare de text în captions).
- `text_add` (timp de timeline!):
  - hook text în primele 0-2.5s, max 6 cuvinte, `position="top"`
  - CTA la final: ultimele 2-3s ("Follow pentru partea 2"), doar dacă brief-ul cere
- Nu pune text peste zona unde sunt captions (`bold_center`/`karaoke` stau în treimea de jos → text sus).
- **2+ vorbitori** (podcast, interviu, dialog): după `diarize`, folosește `captions_add(..., speaker_colors=true)`.
  Fiecare vorbitor are culoarea lui (A alb, B galben, C cyan...), iar o captură nu amestecă niciodată doi vorbitori.
- Fără emoji în text (fontul poate să nu le aibă).
- **Brand**: dacă clientul are culori / font, `brand_captions` (se aplică pe stilul ales, nu îl înlocuiește).
  Culorile per vorbitor (`speaker_colors`) au prioritate față de culoarea textului din brand.
