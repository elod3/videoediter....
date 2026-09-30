---
name: qa-and-delivery
description: Verificarea finală înainte de livrare către client - rulează QA obiectiv, repară problemele, decide când video-ul e gata. Folosește la finalul oricărei editări.
---

# QA & livrare

1. `render(preview=false)` → `qa_check()`.
2. Pentru fiecare problemă din `issues`:
   | Problemă | Fix |
   |---|---|
   | durata ≠ timeline | re-randează o dată; dacă persistă, raportează bug |
   | loudness în afara țintei | verifică dacă e muzică prea tare (`music_set` mai jos), re-randează |
   | true peak > -0.5 | scade `volume_db` la muzică cu 3 dB |
   | cadre negre | găsește clipul la acel timp (`timeline_view`) și `clip_trim` / `clip_remove` |
   | liniști > 1.5s | `range_remove` pe intervalul respectiv (e timp de timeline) |
3. Maxim 3 bucle. După a treia, livrează cu lista problemelor rămase.
4. Checklist subiectiv (răspunde da/nu în raport):
   - Primele 2 secunde au hook (vizual sau vorbit)?
   - Există tăieturi în mijlocul cuvintelor?
   - Subiectul e în cadru pe tot parcursul (vertical)?
   - Durata respectă brief-ul?
5. Raport final: cale, durată, format, 3-5 bullet-uri cu ce s-a făcut, probleme rămase.

## Brand și livrare

- **Brand** doar dacă clientul a dat logo / culori / font / intro-outro (sau brief-ul o cere). Aplică-l ÎNAINTE de
  preview, ca să-l vezi o dată cu `frames_look(asset="render:preview")`:
  - `brand_logo`: colțul opus textului de pe ecran (implicit `tr`); `scale` 0.08-0.15, `opacity` 0.7-0.9.
    Pe 9:16 evită `br` (acolo stau butoanele TikTok/Reels).
  - `brand_captions`: text deschis + contur închis (sau invers). La karaoke `highlight` = culoarea de accent a brandului.
  - `brand_intro_outro`: doar clipuri date de client; durata livrată crește (`qa_check` ține cont).
- **Livrare pe platformă**: în loc de `render(preview=false)`, `export_preset(platform)` pentru fiecare platformă
  cerută (fișiere `<platform>.mp4`). Citește `warnings`: format schimbat → `auto_reframe` și re-export;
  durată peste limită → scurtează sau spune-i clientului. Aceleași reguli pentru `qa.issues` ca mai sus.
- `captions_export(fmt="srt")` când se livrează pe YouTube / LinkedIn (subtitrări încărcate separat) sau la cerere.
- `thumbnail_export(title="2-5 cuvinte")` pentru YouTube / long-form; uită-te la imagine înainte de livrare.
