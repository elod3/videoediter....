---
name: motion-graphics
description: Motion graphics, efecte sonore, viteză și efecte vizuale - lower third, titluri, numere animate, callout, liste, CTA, text kinetic, cerc de evidențiere, whoosh/pop/impact, speed ramp, freeze frame, glitch/shake/flash, green screen, stabilizare. Folosește când clientul cere „mai dinamic”, „mai profesional”, „cu grafice”, „ca la MrBeast / Hormozi”, „pune numele lui”, „fă-l să arate scump”, sau când montajul e gata și are nevoie de finisaj.
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
- După orice schimbare de viteză: `captions_add` din nou.

## Efecte vizuale (`clip_fx`), cu măsură
- **`flash`:** tăietură-șoc, începutul hook-ului.
- **`shake`:** pe impact (0.3-0.8 s de clip, taie clipul întâi).
- **`glitch`:** tranziție de subiect în conținut tech / gaming.
- **`bw` / `vintage`:** flashback, „înainte”.
- **`blur`:** fundal sub un title_card.
- **`vignette`, `grain`, `sharpen`:** finisaj discret.
- **Nu pune efecte pe tot clipul și nu mai mult de 2 pe același clip.**

## Stabilizare și green screen
- `stabilize(asset)` doar când se vede tremurul (frames_look / clientul zice). Durează cam cât clipul.
- `broll_key(broll_id, "#00FF00")` când B-roll-ul e filmat pe verde (persoană peste montaj). Verifică marginile.

## Verificare
`render(preview)` → `frames_look(asset="render:preview")`. Verifică:
- graficele nu acoperă fețe sau subtitrări;
- textul se citește;
- cifrele sunt corecte.

Apoi `qa_check`.
