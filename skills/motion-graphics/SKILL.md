---
name: motion-graphics
description: Motion graphics, efecte sonore, viteză și efecte vizuale - lower third, titluri, numere animate, callout, liste, CTA, text kinetic, cerc de evidențiere, linii/grilă care se desenează (hartă/schemă/structură), carduri de date, citat cu autor, before/after, număr de capitol, titlu dezvăluit de mască, typewriter, pastilă de valoare, compoziție liberă (poziție/scară/rotație/opacitate cu clip_animate, lanț de efecte cu fx_chain, text liber text_overlay), whoosh/pop/impact, speed ramp, freeze frame, glitch/shake/flash, green screen, stabilizare. Folosește când clientul cere „mai dinamic”, „mai profesional”, „cu grafice”, „ca la MrBeast / Hormozi”, „pune numele lui”, „fă-l să arate scump”, sau când montajul e gata și are nevoie de finisaj.
---

# Motion graphics și sound design

Graficele și efectele servesc povestea. **Regula de aur:** fiecare element are un motiv în conținut
(un nume, o cifră, o idee cheie, o schimbare de subiect). Fără motiv = zgomot.

## Grafice (`graphic_add`, timp de montaj)

| kind | când | durată |
|---|---|---|
| `lower_third` | prima apariție a unei persoane: text=nume, subtext=rol | 3-4 s, în primele 5 s de vorbire a ei |
| `title_card` | hook text în primele 2 s, capitole, final | 1.5-3 s |
| `counter` | o cifră spusă în clip („am ajuns la 12.500 de lei”): pornește când se spune cifra | 2-3 s |
| `callout` | arată ceva pe ecran (produs, detaliu): x,y = punctul | 2-3 s |
| `circle` | evidențiază un obiect / o zonă: x,y, size | 1.5-2.5 s |
| `list` | enumerare spusă („trei lucruri: …”): items apar pe rând, pe cuvintele din transcript | cât durează enumerarea |
| `kinetic` | o frază-cheie cuvânt cu cuvânt (hook, citat) | 2-4 s |
| `cta` | îndemn (urmărește, link în bio): ultimele 3-5 s, sau după valoarea principală | 2-4 s |
| `progress_bar` | tutoriale / liste lungi: toată durata | tot clipul |
| `line_grid` | linii/grilă care se desenează progresiv: hartă, schemă, structură, tabel, plan | 2-4 s |
| `spec_card` | card de date (titlu + rânduri etichetă/valoare): specificații, fișă tehnică, sumar | 3-5 s |
| `quote_card` | citat (text) + autor (subtext), semn mare de citat; editorial | 3-4 s |
| `before_after` | compară două jumătăți ale cadrului (render/realitate, înainte/după); etichete text/subtext | 2-4 s |
| `chapter_num` | număr mare de capitol (value_to 1-99) + linie + titlu (text); intră cu wipe | 2-3 s |
| `mask_reveal` | titlu dezvăluit de o mască care culisează (nu pop, nu fade simplu) | 2-3 s |
| `typewriter` | text scris literă cu literă, cursor care clipește la final | 2-4 s |
| `stat_badge` | pastilă mică de colț cu o valoare/etichetă, intrare calmă | 2-3 s |

- **Text în spatele persoanei** (`behind=True` pe title_card / kinetic / counter / list / mask_reveal / chapter_num / quote_card):
  1-3 cuvinte uriașe, centrate, pe un cadru cu persoana la bust, în mijloc. E efectul-vedetă: o dată, maxim de
  două ori, pe clip (hook sau dezvăluire).
- **Tipuri de date / editoriale** (`line_grid`, `spec_card`, `quote_card`, `before_after`, `chapter_num`, `mask_reveal`,
  `typewriter`, `stat_badge`): mai calme, pentru firme, explicații, showreel, educație. Cifrele și etichetele vin din
  conținut (nu inventate). `spec_card` cere text (titlu) și items (rânduri `etichetă valoare`); `chapter_num` cere
  `value_to` (1-99) și text (titlul); `quote_card` cere text + subtext (autor); `typewriter` și `mask_reveal` cer doar text.

Reguli:
- **Timpii vin din transcript.** Graficul apare pe cuvântul care îl justifică, nu „cam pe acolo”.
- **Maxim un grafic mare pe ecran odată.** Nu pune `title_card` peste `list`.
- **Subtitrările stau jos/centru:**
  - pune graficele în zona liberă (`upper_left`, `top`);
  - cu `bold_center`, evită `center`;
  - `lower_third` stă stânga-jos: mută subtitrările mai sus sau pune-l `upper_left`.
- **Densitate:** un short de 30-60 s = 2-5 grafice. Un video de 10 min = lower third-uri + capitole + câteva cifre.
- **Culoarea vine din brand;** `color` doar dacă clientul cere.
- **x,y (callout, circle) le iei din `frames_look` pe cadrul respectiv:** 0,0 = stânga-sus, în coordonatele cadrului final.

## Efecte sonore (`sfx_auto`, `sfx_add`)
- După tranziții și grafice: `sfx_auto()`. Pune whoosh pe tranziții, swipe pe punch-in, impact/pop/ding pe grafice.
- Manual doar unde are sens:
  - `riser` în 1-1.5 s dinaintea unei dezvăluiri;
  - `bass_drop` / `impact` pe dezvăluire;
  - `click` pe elemente de UI.
- Volum -8..-14 dB: se aud, dar nu acoperă vocea. Pe podcast / interviu calm: puține sau deloc.
- Dacă clientul a dat un fișier SFX, îl folosești cu `sfx_add(kind="a4", ...)`.

## Viteză
- `speed_ramp(1 → 2.5)` pe B-roll / acțiune înainte de o tăietură = energie. `speed_ramp(2.5 → 0.5)` pe impact.
- `speed_set(0.5)` = slow motion pe momente vizuale (sport, reacție), **nu pe vorbire**.
- `speed_set(1.1-1.2)` pe un vorbitor foarte lent, doar dacă vocea rămâne naturală (verifică preview-ul).
- `freeze_frame(clip, 1-2)` + `title_card` / `callout` peste = moment de „stop, uite”.
- După o schimbare de viteză, subtitrările și graficele se mută singure; verifică-le în preview.

## Efecte vizuale (`clip_fx`), cu măsură
- **`flash`:** tăietură-șoc, începutul hook-ului.
- **`shake`:** pe impact (0.3-0.8 s de clip, taie clipul întâi).
- **`glitch`:** tranziție de subiect în conținut tech / gaming.
- **`bw` / `vintage`:** flashback, „înainte”.
- **`blur`:** fundal sub un title_card.
- **`vignette`, `grain`, `sharpen`:** finisaj discret.
- **Nu pune efecte pe tot clipul și nu mai mult de 2 pe același clip.**

## Fundal fără green screen (`background`)
- Pe talking head:
  - `background(clips, "blur")`: mod portret, pentru cameră de telefon sau cadru dezordonat;
  - `"color", "#101418"`: look de studio;
  - `"asset", "a3"`: fundal de brand sau o poză.
- Decuparea e AI locală (MODNet): se descurcă bine cu o persoană la bust. Poate greși la mâini rapide, obiecte ținute
  în mână sau mai multe persoane: verifică marginile cu `frames_look` și spune-i clientului dacă nu arată curat.

## Stabilizare și green screen
- `stabilize(asset)` doar când se vede tremurul (frames_look / clientul zice). Durează cam cât clipul.
- `broll_key(broll_id, "#00FF00")` când B-roll-ul e filmat pe verde (persoană peste montaj). Verifică marginile.

## Compoziție liberă (nu doar șabloane)
Când șablonul nu ajunge, compui liber cu trei tool-uri (toate randate de ffmpeg, cu validare strictă):
- **`clip_animate(clip_id, keyframes)`** — poziție, scară, rotație și opacitate în timp pe ORICE clip.
  `keyframes` = listă JSON de `{t, x, y, scale, rot, opacity}` (t = secunde de la începutul clipului; x,y centrul
  clipului 0..1; scale cât din cadru; rot grade; opacity 0..1). Interpolare liniară între puncte, capetele constante.
  Ex. imagine care intră mică și crește: `[{"t":0,"scale":0.5,"opacity":0},{"t":1.5,"scale":1,"opacity":1}]`.
- **`fx_chain(clip_id, effects)`** — lanț de efecte parametrizate, din LISTĂ ALBĂ (nu filtre arbitrare):
  brightness, contrast, saturation, gamma, hue, blur, sharpen, vignette, grain, posterize, zoom, mirror,
  flip_vertical, sepia. JSON `[{name, params}]` sau text `'brightness:value=0.1|blur:sigma=8|zoom:value=1.4'`.
- **`text_overlay(start, end, text, x, y, size, color, anim, anim_dur)`** — text liber: poziție (x,y 0..1) sau
  `position`, mărime, culoare #RRGGBB și animație de intrare/ieșire: none / fade / pop / slide_up / slide_left / wipe.
Reguli: compoziția liberă se folosește cu măsură (e efect, nu fundal); verifică mereu pe preview cu `frames_look`;
nu combina `clip_animate` cu `speed` pe același clip (timpul keyframe-urilor ar ieși altfel).

## Stiluri de montaj (`style_recipe`)
Pe lângă hormozi / mrbeast / tiktok / podcast / cinematic există **`editorial`**: paletă desaturată + un singur
accent, ritm lent, tranziții dissolve, fără shake/glitch. Bun pentru firme, brand, explainer, interviu calm.

## Verificare
`render(preview)` → `frames_look(asset="render:preview")`. Verifică:
- graficele nu acoperă fețe sau subtitrări;
- textul se citește;
- cifrele sunt corecte.

Apoi `qa_check`.
