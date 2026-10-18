---
name: beat-montage
description: Montaj de produs, mașină, imobil sau eveniment pe muzică, la nivel de „car edit” profesionist - tăieturi pe grila de beat cu lungimi variabile (1/2/4 beat-uri), mișcare de cameră pe fiecare shot, whip-uri rare, RGB split, speed ramp, grade rece și contrastat, sfx. Folosește când clientul dă filmări fără vorbire + o piesă și zice „car edit”, „reel de produs”, „teaser imobil”, „aftermovie”, „pe beat”, „ca în clipul ăsta” (referință cu tăieturi rapide), sau când `beat_montage` simplu iese plat.
---

# Montaj pe beat, nivel pro

`beat_montage` cu `beats_per_shot` simplu face tăieturi egale: arată ca un slideshow. Cu `pattern` și `lead` taie
ca un editor (vezi §3). Un car edit bun are **ritm variabil
care accelerează spre un punct culminant, mișcare în fiecare shot și puține efecte, puse cu motiv**. Măsurători pe
referința Porsche GT3 în `references/breakdown-Dd6peYGIFjr.md`. Ce nu se poate face încă: `GAPS.md`.

## 0. Reguli măsurate (nu le inventa)

- Tăieturile cad pe grila de beat, dar **cu 0.02-0.05 s ÎNAINTE de beat** (1-2 cadre): ochiul vede noul shot exact
  când lovește sunetul. Cu beat-ul exact pe tăietură, pare târziu.
- Lungimile shot-urilor sunt multipli de beat: **1, 2, 4** (rar 3). Nu 1.5, nu „cam o secundă”.
- Curba ritmului: intro 2-3 shot-uri lungi (2-4 beat-uri) -> **rafală de shot-uri de 1 beat** (6-8 la rând) ->
  2 -> 4 -> shot lent de detaliu (3 beat-uri) -> bookend (revii la cadrul de început, 2 beat-uri).
- Fiecare shot conține **mișcare de cameră** (push-in, orbită, glisare) care pornește tare și se așază (ease-out).
  Cadru static = mort.
- Tranziții „de post” doar 1 din ~6 shot-uri (whip / RGB split) și mereu pe un shot de 2-4 beat-uri.
  Restul sunt tăieturi dure. Efectul „wow” din referință vine din mișcarea camerei și din ritm, nu din filtre.
- Alternează luminozitatea: exterior luminos / interior întunecat / detaliu luminos. Nu pune 3 shot-uri la rând cu
  aceeași lumină și același unghi.
- Fără text, fără subtitrări. Muzica e singurul sunet (clipul original: fără sunet de motor).
- Look: saturație scăzută (~0.8), umbre ușor reci, negrii adânci, albii curați, fără grain vizibil.

## 1. Pregătire

1. `asset_add` pe toate filmările și piesa. `asset_role(asset, "broll")` pe ce nu e piesă dacă vrei. Piesa: orice
   asset cu audio (nu cere rol).
2. `beats_detect(music)` -> BPM, `beat-uri`, `downbeat-uri`. Notează lista. Încredere < 30% e normală pe piese
   cu producție dens; verifică după ureche pe un render scurt.
3. `frames_look(asset, cols=4, rows=3)` pe fiecare filmare. Fă lista de shot-uri bune: detaliu (emblemă, far, roată,
   mâner), mișcare (orbită, push), exterior vs interior. Notează `src_in` unde mișcarea e frumoasă.
4. `timeline_format(fmt="9:16", fps=30)` (sau 16:9 / 1:1 după cerere).
5. Referință dată de client: `reference_analyze` + `frames_look`; ritmul lor în cifre, nu din impresie.

## 2. Planul de ritm (scrie-l înainte să tai)

Alege `total_beats` (17 s la 115 BPM = 33 beat-uri). Scrie planul ca listă de lungimi, suma = total:

```
pickup 0.5 | 1 | 2 | 4 | 4 | 2 | 1 1 1 1 1 1 | 2 | 1 1 | 4 | 3 | 2     (exemplu GT3, 17 s)
```

Sub 15 s: 1-2 shot-uri de 4. Peste 30 s: repetă „rafală + respirație” (ex. 1x6, apoi 4, apoi 1x4, apoi 2).
Rafala de shot-uri de 1 beat pică pe refren / drop; respirația (4 beat-uri) pe strofă.

## 3. Construiește timeline-ul (rețeta de bază, tool-uri reale)

**Rapid și corect:** `beat_montage(music, sources, pattern="4,2,2,1,1,1,1,1,1,2", lead=0.03, max_duration=17)`.
Tiparul se repetă până la `max_duration`; `lead=0.03` pune fiecare tăietură cu un cadru înaintea beat-ului. Apoi
pașii 4-5 de mai jos (ordinea shot-urilor) și §4 (mișcare). Shot-urile sunt alese din tăieturile de scenă ale
surselor, intercalate; dacă vrei shot-uri anume pe poziții anume, construiește manual:

1. Pentru fiecare shot din plan: capetele = `beats[i] - 0.03` și `beats[j] - 0.03` (din `beats_detect`).
   Durata = diferența. Calculează din lista de beat-uri, nu cu `60/BPM * n` (altfel driftează).
2. `clip_add(asset, src_in, src_out)` în ordine (index implicit = la final). `src_out - src_in` = durata.
   Dacă lipsește 0.03 s, shot-ul următor se aliniază singur cu beat-ul.
3. `music_set(asset=music, volume_db=0, duck=false, src_in=<beats[start] - 0.03 - pickup>)`.
   Timpul 0 al montajului trebuie să cadă `pickup` secunde înainte de primul beat din plan.
4. Mută/șterge cu `clip_move`, `clip_remove`; retaie cu `clip_trim`. `timeline_view` la final: fiecare început de
   clip trebuie să fie `beat - 0.03` (+- 0.02).
5. Alternanța: aranjează shot-urile cu `clip_move` ca două shot-uri vecine să difere (lumină, unghi, mărime).
   Primul shot = cel mai puternic vizual; ultimul = revenire la primul (bookend, bun pentru loop).



## 4. Mișcare pe fiecare shot

Pe fiecare clip: `clip_keyframes(clip_id, keys, motion_blur=true)`, timp din clip:

- **Punch-in care se așază** (default, ~80% din shot-uri):
  `[{"t":0,"zoom":1.3,"cx":0.45,"cy":0.4,"ease":"expo"},{"t":<durata>,"zoom":1.0}]`. Alternează direcția (`cx` 0.45 / 0.55).
- **Push lent de detaliu** (shot-ul de 3-4 beat-uri): `[{"t":0,"zoom":1.0},{"t":<durata>,"zoom":1.18,"ease":"out"}]`.
- **Ușor tilt** pe interior: adaugă `"rotate":3` la start, `0` la final (cere zoom >= 1.1).
- `motion_blur=true` doar când mișcarea e rapidă (primele 0.2 s). Clipurile deja cu mișcare de cameră reală: zoom mic
  (1.08) sau deloc, ca să nu dublezi.
- Clip static filmat pe trepied: `zoom_animate(clip, zoom_to=1.15)`.

## 5. Tranziții și efecte (cu măsură)

| Moment | Tool |
|---|---|
| Intrare pe shot de 2-4 beat-uri, trecere între două locuri/unghiuri | `transition_set(clip, "whipleft"\|"whipright", 0.2)` |
| Pe drop, sau intrarea în rafală | `transition_set(clip, "glitch", 0.15)` (RGB split + zgomot) sau `fadewhite` 0.15 |
| Zoom prin cadru spre refren | `transition_set(clip, "zoomthrough", 0.3)` |
| Reveal lent | `transition_set(clip, "blurdissolve", 0.5)` |

Reguli tehnice (verificate):
- Tranziția ocupă `[tăietură - d, tăietură]`: noul shot e complet vizibil la tăietură, dar **montajul se scurtează cu d**.
  Compensează: `clip_trim` pe clipul dinainte, `src_out + d`. Altfel tot ce urmează iese din beat.
- Tool-ul sare peste tranziție dacă un clip are < 2*d (ex. clipuri de 0.1 s nu primesc tranziție). Pune tranziții doar pe shot-uri >= 0.5 s.
- `fx`: `clip_fx(clip, "shake")` pe impact (un shot de 1 beat din rafală), `flash` pe primul shot după drop.
  `clip_fx(..., "glitch")` dă RGB split în rafale la 0.6 s: folosește-l pe un singur shot, nu pe toate.
- RGB split / aberație pe margini (cum are referința pe trecerea prin prim-plan): `clip_nodes(clip, graph)` cu
  nod `chromatic` (amount 0.3-0.5), constant pe tot shot-ul.
- **Pulsuri pe beat** (după ce montajul are muzica): `beat_fx(kind="punch", start=<drop>, end=<drop+4>)` = zoom-in
  de 5% care revine în 0.15 s pe fiecare beat al rafalei; `beat_fx(kind="rgb", start, end, every=2)` = RGB split
  3 cadre din două în două beat-uri; `beat_fx(kind="flash", start, end=start+1)` = flash pe primul beat după drop.
  Maxim 2 porțiuni cu pulsuri într-un clip de 17 s; pe strofă, nimic.
- Tranziții noi: `invertwhip` (whip + 2 cadre în negativ, 0.2 s) și `chromawhip` (whip cu RGB split, 0.25 s).

## 6. Viteză

- `speed_ramp(clip_id, speed_from=1.0, speed_to=2.5)` înainte de o tăietură: rampă LINĂ (viteza se schimbă continuu).
  Scurtează clipul: `durata = D/(S1-S0)·ln(S1/S0)` (1 -> 3 pe 2 s de sursă = 1.10 s). Alege `src_out` ca tăietura să
  rămână pe beat și verifică în `timeline_view` (apare „rampă 1x→3x”). Sunetul clipului merge cu viteza medie: pe
  rampe ține clipul mut, cu muzica.
- `speed_set(clip, 0.5)` pe detaliu lent (macro pe emblemă, literele de pe spate). Doar pe filmări de 50/60 fps; la 25/30
  fps iese sacadat (verifică `asset_list` pentru fps).
- Nu pune ramp pe fiecare shot: 1-2 în tot clipul.

## 7. Culoare și finisaj

1. `color_grade(asset="all", preset="contrast", saturation=0.8, temperature=-2)` (rece, negrii adânci). Nu `teal_orange`
   la mașini albe/gri: colorează caroseria. Pentru un client cu referință: `color_match(strength=0.7)` apoi ajustezi.
2. Un grade pe toate filmările, ca să nu sară între camere. Verifică `frames_look(asset="render:preview")`.
3. `clip_nodes(clip_ids, graph)` cu `glow` (threshold 0.78, size 2, intensity 0.3) pe exteriorul însorit
   (reflexii pe vopsea). Halation roșu: după GAPS (1.4).
4. `enhance(sharpen=0.4)` dacă filmarea e moale. `clip_fx "grain"` doar la look vintage cerut.
5. `stabilize(asset)` pe filmările din mână (nu pe cele de gimbal).

## 8. Sunet

- Muzica la 0 dB (nu ducking, nu voce). `music_fit` doar dacă piesa e mai scurtă decât montajul.
- `sfx_add("whoosh", at=<tăietura - d>, volume_db=-12)` pe fiecare whip; `sfx_add("impact" | "bass_drop", at=<drop>, -10)`
  pe primul beat al rafalei. `sfx_add("riser", at=<drop - 1.5>)` înainte de drop. Maxim 4-6 sfx într-un clip de 17 s.
  `sfx_auto(transitions=true, graphics=false, punch_ins=false)` pune whoosh pe tranziții.
- Final: fade-out de muzică pe ultimul beat (`music_set` îl face automat).

## 9. Verificare (obligatorie)

1. `render(preview=true)` -> `frames_look(asset="render:preview", cols=6, rows=4)`: ritmul se vede ca densitate de
   schimbări; primul cadru = cel mai bun.
2. `timeline_view`: începuturile de clip vs `beats`: abatere <= 0.05 s; lungimile = planul.
3. Niciun shot repetat; niciun shot sub 0.4 s fără mișcare; lumina alternează.
4. `qa_check` pe fișierul final.

## Variante

- **Imobil** (apartament, casă): shot-uri mai lungi (2-4 beat-uri), push-in lent și glisări, fără rafală; rafala doar
  pentru „detalii” (mâner, finisaj). Grade cald, `preset="luminos"`. Ordine: fațadă -> intrare -> living -> detalii -> exterior.
- **Produs** (cosmetice, gadget): macro + rafală de detalii; fundal curat; text/preț doar la final cu `graphic_add("title_card")`.
- **Eveniment / aftermovie**: shot-uri cu oameni la 2 beat-uri, rafală pe refren cu momentele de vârf; `audio` original
  sub piesă cu `beat_montage(keep_audio=true)` dacă clientul vrea atmosfera.
- **Vertical vs orizontal**: planul de ritm rămâne; la 16:9 zoom-urile pot fi mai mici (1.15).

## Nu face

- Nu pune aceeași tranziție de mai mult de 2 ori. Nu pune efecte pe fiecare tăietură.
- Nu tăia pe `beats` brute fără offset -0.03.
- Nu folosi `beat_montage` cu `beats_per_shot=1` pe tot clipul (obositor); rafala e doar o parte.
- Nu promite clientului halation până nu e implementat (GAPS).
- Nu pune `beat_fx` pe tot clipul: pulsul constant devine zgomot vizual.
