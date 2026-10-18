---
name: screen-recording
description: Tutoriale, demo-uri de aplicații / SaaS, prezentări de produs și cursuri filmate de pe ecran (OBS, Loom, QuickTime), cu sau fără camera persoanei. Zoom automat pe acțiune, tăierea așteptărilor, subtitrări, evidențieri. Folosește când clientul urcă o înregistrare de ecran sau zice „tutorial”, „demo”, „screen recording”, „prezentare de aplicație”, „curs”, „walkthrough”.
---

# Înregistrări de ecran

## Pași

1. `media_analyze` → `transcript_get`. Pe ecran, pauzele lungi sunt așteptări (se încarcă o pagină): taie-le cu
   `cut_silences(min_silence=0.8)`, dar NU sub 0.5 s: privitorul trebuie să vadă ce s-a schimbat pe ecran.
2. Scoate greșelile („stai, nu, am greșit”, click pe pagina greșită) cu `cut_words` pe zonele respective.
3. **Zoom automat:** `screen_zoom(max_zoom=1.8)` urmărește cursorul, click-urile și textul tastat, apoi revine la
   ecranul întreg la scroll / pagină nouă. Rulează-l DUPĂ tăieturi.
   - Text mic (cod, tabele, setări): `max_zoom=2.0`.
   - Mult scroll / video pe ecran: poate da puține zoom-uri. E normal.
   - Verifică 3-4 momente cu `frames_look` pe preview: zona importantă trebuie să fie în cadru.
4. **Format:** YouTube / curs: 16:9. Pentru shorts din tutorial, `timeline_format("9:16", fill="blur")` păstrează
   tot ecranul lizibil; cu `crop`, zoom-ul decide ce se vede.
5. `captions_add(style="classic_bottom")` pe 16:9 (nu acoperi centrul ecranului). Pe 9:16, `boxed`.
6. Evidențieri: `graphic_add` de tip `callout` / `circle` pe butonul important, sincron cu cuvântul din transcript
   („apăsați pe **Salvează**”). Un `sfx_add("click", t)` discret la click-urile cheie.
7. Capitole (`chapters_set`) la tutorialele peste 3 minute: fiecare pas mare e un capitol.
8. Cu persoana în colț (webcam suprapusă): nu atinge colțul ei cu grafice.

## Nu face

- Nu pune muzică tare peste explicații (`music_set` cu volum -26 dB sau deloc).
- Nu grăbi (`speed_set`) părțile în care se tastează date importante: privitorul trebuie să le poată citi.
