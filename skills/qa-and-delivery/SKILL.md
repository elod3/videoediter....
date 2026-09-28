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
