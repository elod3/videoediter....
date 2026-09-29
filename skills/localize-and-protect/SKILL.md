---
name: localize-and-protect
description: Dublaj în altă limbă cu voce AI, cenzură cu bip și ascunderea fețelor / zonelor (blur, pixel). Folosește când clientul cere „fă-l în engleză / maghiară”, „dublează”, „traducere cu voce”, „cenzurează înjurăturile”, „bleep”, „pune blur pe fețe / pe trecători / pe numărul mașinii / pe ecran”, „anonimizează”, sau când vezi în cadru date personale (plăcuțe, adrese, ecrane cu date, copii) pe care clientul probabil nu vrea să le publice.
---

# Localizare și protecție

## Cenzură (`censor_words`)

1. `transcript_get(asset)`. Fără listă de la client, rulează `censor_words(asset=...)`: lista încorporată de
   înjurături (ro, en, hu). Cu listă: `censor_words(words="w12,w40")` sau `words="cuvânt,prefix*"`.
2. `mode="bleep"` (TV, implicit) sau `mode="mute"` (liniște, mai discret pentru vloguri).
3. Citește raportul: dacă a prins un cuvânt nevinovat, `undo` și dă id-urile exacte.
4. Rulează DUPĂ tăieturi și DUPĂ `captions_add`: subtitrările arată „f***”.
5. Durata nu se schimbă. Dacă clientul vrea cuvântul SCOS de tot, folosește `cut_words`, nu cenzura.

## Fețe și zone ascunse

- **Trecători, copii, oameni fără acord:** `blur_faces(clip_ids, keep_main=True)`. Persoana principală (cea mai
  mare față) rămâne vizibilă. Toată lumea: `keep_main=False`.
- **Zone fixe** (număr de mașină, ecran cu date, adresă, logo străin): `frames_look` pe asset, estimezi
  dreptunghiul ca fracții din cadrul SURSĂ, apoi `blur_region(start, end, x, y, w, h)`. Pune o marjă de ~20%.
- `style="pixel"` arată ca la știri; `blur` e mai discret.
- **Verifică obligatoriu:** randează un preview și `frames_look` pe 3-4 momente. Detectorul poate rata fețele
  din profil, foarte mici sau în mișcare rapidă: pe acelea pune `blur_region`.
- Nu merge pe clipuri split-screen.

## Dublaj (`dub`)

1. Montajul trebuie să fie FINAL (tăieturi, ordine, viteză). Vocea dublată nu urmează tăieturile făcute după.
2. `captions_add` pe original (dacă nu există), apoi `captions_list`: ai replicile cu timpii de montaj.
3. Traduci replicile natural, nu cuvânt cu cuvânt, și **cam la fel de lungi** ca originalul. Engleza e de obicei
   mai scurtă decât româna, iar germana mai lungă. Grupează 1-3 subtitrări într-o replică (o frază întreagă).
4. `dub(segments="0.00-2.10|Hello everyone...\n2.40-5.80|Today I'll show you...", lang="en")`.
   Replicile prea lungi sunt grăbite automat până la 1.5x. Dacă raportul zice „PREA LUNGI”, scurtează acele
   replici și rulează din nou.
5. `original_db=-100` (implicit): vocea originală oprită. Cu muzică / ambient în clip, `-24` păstrează
   atmosfera, dar se aude și vocea originală încet. Spune-i clientului care e compromisul.
6. Subtitrările existente se refac automat în limba nouă. Muzica (`music_set`) face ducking sub dublaj.
7. Limbi: ro, en, hu, de, es, fr, it (voce locală, gratuită). Buzele NU se sincronizează: spune-i clientului
   că e dublaj de tip documentar / voice-over, nu lip-sync.
