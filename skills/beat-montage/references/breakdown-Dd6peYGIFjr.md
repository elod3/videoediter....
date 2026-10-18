# Breakdown: Porsche GT3 car edit (Dd6peYGIFjr.mp4, yonatan_raymond)

Date măsurate cu ffmpeg + `vedit.beats`, nu estimate. Corecție față de brief: fișierul e **59.94 fps** (1080x1920, 17.0 s,
1019 cadre), nu 29.97. Audio: doar muzică (AAC mono-ish ~67 kbps), fără sunet de motor.

## Muzica
- `vedit.beats.detect`: **114.9 BPM** (perioadă 0.5217 s), încredere 27%. Beat-uri: 0.28, 0.81, 1.32, 1.86 ... (grila 0.28 + k*0.5217).
  Downbeat-uri (estimate): 1.32, 3.44, 5.50, 7.59, 9.68, 11.77, 13.86, 15.95.
- Onset-uri joase (kick) detectate independent cu FFT: 0.26, 3.9, 5.99, 7.04, 9.13, 9.65, 15.38, 16.3, 16.7.
  Tăieturile mari (3.92, 6.01, 7.04) cad pe ele.

## Tăieturi (scene detect 0.07-0.18, 59.94 fps) vs beat-ul cel mai apropiat
| # | Tăietură (s) | Beat | Offset | Durata shot-ului precedent |
|---|---|---|---|---|
| 1 | 0.27 | 0.28 | -0.01 | 0.27 (pickup, sub 1 beat) |
| 2 | 0.78 | 0.81 | -0.03 | 1 beat |
| 3 | 1.84 | 1.86 | -0.02 | 2 beat-uri |
| 4 | 3.92 | 3.95 | -0.03 | 4 beat-uri |
| 5 | 6.01 | 6.04 | -0.03 | 4 beat-uri |
| 6 | 7.04 | 7.08 | -0.04 | 2 |
| 7 | 7.57 | 7.59 | -0.02 | 1 |
| 8 | 8.09 | 8.13 | -0.04 | 1 |
| 9 | 8.61 | 8.64 | -0.03 | 1 |
| 10 | 9.14 | 9.17 | -0.03 | 1 |
| 11 | 9.66 | 9.68 | -0.02 | 1 |
| 12 | 10.19 | 10.19 | 0.00 | 1 |
| 13 | 11.23 | 11.26 | -0.03 | 2 |
| 14 | 11.75 | 11.77 | -0.02 | 1 |
| 15 | 12.26 | 12.31 | -0.05 | 1 |
| 16 | 14.35 | 14.40 | -0.05 | 4 |
| 17 | 15.90 | 15.95 | -0.05 | 3 |

**Toate cele 17 tăieturi cad cu 0 până la 0.05 s (medie ~0.03 s = 2 cadre la 60 fps) înaintea beat-ului.** Lungimi: 1, 1, 2, 4, 4,
2, 1x6, 2, 1, 1, 4, 3, 2 (ultimul shot 15.90-17.00). Suma 33 de beat-uri.

## Structura, shot cu shot (conținut din cadre; momentele sunt din detecție, conținutul din contact sheet 4 fps)
| Timp | Plan | Mișcare |
|---|---|---|
| 0.00-0.27 | cadru larg frontal, mașina albă în fața showroomului, umbre de copac | static, 0.27 s: „carte de vizită” (revine la final) |
| 0.27-0.78 | capotă, aproape, înclinat, plăcuță GT3 | push-in rapid, se așază |
| 0.78-1.84 | emblema Porsche (macro) -> fantele capotei | push + glisare laterală |
| 1.84-3.92 | far frontal (macro) -> 3/4 față cu roata -> aceeași mișcare continuă TRECE PRIN SPATELE unei alte mașini în prim-plan (ea ocupă cadrul = „wipe” natural) -> eleron / spate | o singură mișcare de gimbal de 4 beat-uri, fără tăiere |
| 3.92-6.01 | spate larg, întunecat în umbră; o a doua mașină albă intră în cadru din dreapta, cu franjuri RGB pe marginile ei; apoi profil lateral cu roata | cameră aproape fixă, mișcarea o face mașina din prim-plan |
| 6.01-7.04 | eleronul în prim-plan cu fundal bokeh (clădire), apoi acoperiș carbon | push scurt |
| 7.04-7.57 | interior: ecran + butoane, schimbător manual | push / glisare |
| 7.57-8.09 | schimbătorul (cusătură galbenă) | glisare |
| 8.09-8.61 | consolă + volan | glisare |
| 8.61-9.14 | bord, volan, cadran | push |
| 9.14-9.66 | scaun carbon (cochilie) | push |
| 9.66-10.19 | tetieră cu „GT3” auriu | push lent |
| 10.19-11.23 | tetieră mai larg, centura galbenă | mișcare lentă |
| 11.23-11.75 | roll cage (bară de protecție) | push |
| 11.75-12.26 | interior larg din ușă | glisare |
| 12.26-14.35 | iese afară: față larg în fața showroomului -> push-in rapid -> trece pe lângă eleron în prim-plan (wipe) -> coada | mișcare continuă de 4 beat-uri |
| 14.35-15.90 | litere „GT3” + stopuri + țevi, macro | aproape static, drift lent; câteva cadre duplicate = camera aproape oprită, nu tăieturi |
| 15.90-17.00 | revenire la cadrul larg frontal din primul cadru (bookend) | push lent de 1 s |

## Tranziții
- **Zero tranziții de post vizibile pe tăieturi** (toate sunt tăieturi dure, 17/17). Tranzițiile „care par efect” sunt:
  (a) mașina din prim-plan care acoperă cadrul (1.84-3.92, 4.9-5.6, 13.2-13.6) = wipe prin conținut, cu fund întunecat;
  (b) whip / blur de mișcare într-un shot continuu (cadre cu blur orizontal ~2.4-2.6 s);
  (c) franjuri RGB (aberație cromatică pe contururi) pe marginile contrastate în aceleași treceri: constante cât ține trecerea, nu pulsate.
- Concluzie pentru vedit: efectul se obține în primul rând din **filmare** (mișcări continue, prim-planuri care ocupă cadrul).
  Din post: `transition_set whipleft/right 0.2` pe cadrele lipite dintr-o mișcare similară (stânga-dreapta) + nod `chromatic` 0.3-0.5.

## Mișcare, viteză
- Energie de mișcare (diferență medie între cadre; ferestre de 15 cadre = 0.25 s): alternează 15-30 (început de shot) cu 2-6
  (sfârșit): fiecare shot **pornește repede și se așază** (ease-out/expo). Cea mai mare mișcare: primele 1.5 s, imediat după tăieturile de la 14.35 și 15.90 s.
- Cadre duplicate (diferență < 0.05): 16 din 1019, la ~6.8 s, 15.07-15.28 s și 16.80-16.97 s (cadru ținut / drift lent). Nu există slow-motion
  generalizat. Speed ramp vizibil nu a fost măsurat clar: mișcările rapide pe început de shot pot fi viteză mărită, dar
  nu se poate separa de mișcarea de gimbal. (Verifică înainte să promiți „speed ramp” clientului.)

## Culoare / textură (cifre pe tot clipul, cadre 108x192)
- Luminanță (0-255): p1 = 7, p5 = 11, mediană 68, p95 = 243, p99 = 245. Negrii adânci (nu zdrobiți complet), albii aproape clipați pe caroserie.
- Medie RGB 95/96/98: neutru-rece. Saturație medie (HSV) 0.18: **desaturat**.
- Umbre (Y < 60): R25 G27 B30 = ușor reci. Lumini (Y > 200): R226 G228 B228 = neutre, spre rece.
- Luminanța medie pe secvențe alternează: exterior 140-200 / interior 40-80 / exterior 100-140. Contrastul vine din alternanță.
- **Grain:** nu se vede la 540 px. **Halation / bloom:** reflexii moi pe vopsea, dar fără halo roșu; nu e film emulation.
  **Motion blur:** natural de la obturator (cameră) + blur direcțional pe whip-uri. Adâncime mică de câmp (bokeh pe fundal) pe detalii.
- Franjuri cromatice: doar pe marginile mașinii din prim-plan în whip (fringe de lentilă / efect discret), nu pe tot cadrul.

## Ce înseamnă pentru agent
1. Ritm 1/2/4 pe grila de beat, cu tăietura la beat - 0.03 s.
2. Rafală de 6 shot-uri de 1 beat pe interior (partea cea mai „densă”), încadrată de shot-uri lungi cu mișcare continuă.
3. Bookend: ultimul cadru = primul cadru.
4. Look curat: grade rece, saturație ~0.8, contrast mare. Efectele de post sunt secundare.
5. Filmarea contează: dacă filmările clientului sunt statice, `clip_keyframes` (punch-in expo + motion_blur) înlocuiește mișcarea camerei.
