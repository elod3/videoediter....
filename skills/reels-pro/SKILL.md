---
name: reels-pro
description: Montaj de reels / shorts cu motion graphics „de agenție” (stil Milad Aslani, Barsolmedia): cuvânt uriaș în spatele persoanei, tipografie în 3 registre, cuvinte care orbitează capul, carduri care plutesc, contor de calendar, balon de chat, tranziție cu pixeli, relight/fundal schimbat, sunet pe fiecare lovitură. Folosește-l când clientul cere „reel / short / TikTok cu animații”, „ca la X”, „text în spatele meu”, „text cinetic”, „să nu arate ca făcut de AI”, sau când un montaj iese plat, cu subtitrări și atât. Completează motion-design și motion-graphics; are prioritate la reels verticale cu un vorbitor.
---

# Reels pro

Diferența dintre un reel bun și „slop” nu e câte efecte are. E **o idee per scenă, un singur cuvânt uriaș, 3 registre
de tipografie, mișcare cu greutate (blur → clar, nu fade), sunet pe fiecare lovitură, liniște după lovitură**.
Referințele analizate stau în `references/` (citește `breakdown-DeC-xCeMrS6.md` înainte de primul reel din proiect).
Blocurile noi sunt descrise în `plan-api` (în `motion_blocks`): verifică-le acolo înainte de parametri; dacă un bloc
lipsește, spune-o în raport, nu inventa parametri.

## 0. Înainte să pui orice
1. `transcript_get` și alege **3-6 cuvinte-lovitură** din tot clipul (rezultat, cifră, „stop”, „nimeni”, numele
   ofertei). Restul textului nu primește grafică.
2. Împarte clipul în **scene de 1,8-3 s** (o idee fiecare). Fiecare scenă are: un cuvânt uriaș SAU un obiect-card,
   nu amândouă la același volum.
3. `motion_style(style="reel", palette="auto")` pentru reels cu vorbitor (Anton + Caveat + Montserrat). Pentru
   brand serios păstrezi `iman` / `arhitect`, dar aplici aceleași reguli de mai jos.
4. O culoare de accent per scenă, luată din cadru (haina, fundalul, brandul); restul alb/negru. Maxim un accent
   pe cadru.

## 1. Cele 3 registre (obligatoriu la orice text mare)
| registru | rol | proporție | exemplu |
|---|---|---|---|
| `word` | UN cuvânt condensat ultra-bold, MAJUSCULE sau Titlu | 10-16% din înălțimea cadrului | SELL, GYMS, EXIST |
| `accent` | script / brush, în accent, peste sau sub cuvânt | ~40% din mărimea lui `word` | „California”, „Day” |
| `top` / `bottom` | sans mic, 4-7 cuvinte, încadrează | ~25% din `word` | „Nobody cares what you” |
Raport mic : mare : accent ≈ 1 : 4 : 1,7. Contrast de mărime ȘI greutate ȘI stil. Un singur cuvânt uriaș pe
scenă. Fără al doilea titlu mare, fără 4 fonturi.

## 2. Rețete (timpii sunt în timp de montaj; „t” = momentul în care se rostește cuvântul-lovitură)

### A. Cuvânt uriaș în spatele persoanei („Scripts”, „sell”, „GYMS”)
Când: hook (primele 2 s), dezvăluire a ideii, o dată sau de două ori pe clip, pe cadru cu persoana la bust, cap
liber în mijloc.
```
motion_add(block="stack_title", start=t-0.15, end=t+1.4,
  params={"top":"Nobody cares what you","word":"sell","accent":"","bottom":"","reveal":"blur",
          "position":"center","size":1.0}, behind=true)
sfx_add("impact", t, -10)         # lovitura
sfx_add("whoosh", t-0.15, -14)    # cu 4-5 cadre înainte
```
- Intrare: cuvântul uriaș vine din blur 30 px → 0 în **0,3 s**, ease expo-out, fără bounce; `top` 0,1 s mai devreme,
  cuvânt cu cuvânt (0,1 s/cuvânt). Stă **0,8-1,3 s**, apoi iese în 0,2 s (blur + scale ↑ 1.05).
- Capul/umerii trebuie să acopere 15-35% din partea de jos a literelor. Dacă nu acoperă deloc, nu se vede
  efectul: mută `position` sau micșorează persoana (`reframe(zoom=0.9)` / retușează cadrul).
- Verifică ÎNTÂI `motion_preview` pe 3 momente: masca nu taie părul și mâinile care gesticulează. Dacă o taie,
  nu folosi `behind` pe secvența aia.

### B. Cuvinte pe arc în jurul capului („Stop buying videos instead”)
Când: o frază-manifest de 5-12 cuvinte spusă repede (hook, o „teză”). Cea mai bună pe un talking head apropiat.
```
motion_add(block="orbit_words", start=t0, end=t1,
  params={"text":"Stop buying videos instead","x":0.5,"y":0.30,"radius":0.40,"layout":"arc",
          "emphasis":["Stop","videos"],"times":[0.0,0.3,0.7,1.1,1.8]})   # times din transcript
```
- Un cuvânt = o apariție, **sincron cu vocea** (0,25-0,5 s între cuvinte); cuvântul stă 0,5-0,9 s și iese pe arc.
- `emphasis`: 1-2 cuvinte în accent și mai mari; restul alb. Max 3 cuvinte vizibile simultan.
- `x,y` = centrul capului (din `frames_look`). Fraza trebuie să încapă pe arc fără să acopere ochii/gura.
- Combinație bună: `orbit_words` + `zoom_animate(zoom_from=1.0, zoom_to=1.12)` lent pe același clip.

### C. Carduri care plutesc (dovadă, capturi, produs)
Când: se spune „am făcut X / am primit Y” și clientul are poze/capturi (nu inventa; fără poze nu pui carduri).
```
motion_add(block="float_cards", start=t, end=t+2.2,
  params={"layout":"around","labels":["12.500 lei"],"glow":true},
  images={"card1":"a3","card2":"a4","card3":"a5"})
sfx_add("whoosh", t, -12); sfx_add("pop", t+0.3, -14)
```
- 1-3 carduri. Intră cu whip + blur ~25 px → 0 în 0,3 s, overshoot mic (scală 1.04 → 1.0), apoi plutesc ±6 px
  încet. Rămân 1,6-2,4 s. Nu le pune peste față.
- Micșorarea persoanei (35-45%) ca să facă loc cardurilor e tehnica din referință, dar `clip_keyframes` acceptă zoom ≥ 1: până la implementare (GAPS.md #3) pune cardurile pe părțile libere ale cadrului.

### D. Contor de calendar („1 → 2 → 3 zile”)
```
motion_add(block="day_counter", start=t, end=t+1.8,
  params={"from":1,"to":3,"label":"Zile","title":"Prinde vizualizări","sub":""})
```
Doar când clipul spune o progresie în timp. Peste o tăietură (ascunde saltul). Pagina se răsfoiește în 3 cadre;
sunet: `click` la fiecare pagină.

### E. Balon de chat / card UI („This one tip will change your life”)
```
motion_add(block="bubble", start=t, end=t+1.6,
  params={"text":"Acest sfat","sub":"îți schimbă săptămâna","side":"left","tone":"accent"})
```
Pentru un sfat, o întrebare, o dovadă socială. Pop cu overshoot ~8%. Maxim 2 rânduri.

### F. Comic burst / linii de viteză (momentul „stai, ce?”)
```
motion_add(block="speed_lines", start=t, end=t+0.8, params={"x":0.5,"y":0.35}, behind=true)
motion_add(block="stack_title", start=t, end=t+0.8, params={"word":"STOP"}, behind=true)
```
Max o dată pe clip. Cu `clip_fx(effects="flash")` pe intrare.

### G. Tranziție cu pixeli peste tăietură (schimbare de idee)
```
motion_add(block="pixel_wipe", start=cut-0.25, end=cut+0.25, params={"color":"#E4202F"})
sfx_add("glitch", cut-0.1, -12)
```
Alternativ `transition_set(clip_ids, type="glitch"|"whipleft"|"zoomthrough", duration=0.2)`.
Una la 3-5 tăieturi, nu la toate.

### H. Scena de dezvăluire (hook + payoff)
1. Hook (0-2 s): rețeta A sau B.
2. Dovadă (2-5 s): rețeta C sau `stat` (cifră reală).
3. Pivot: rețeta G.
4. Final (ultimele 2-3 s): `cta` cu acțiune reală. Un end card cu logo (`logo_reveal`) doar dacă clientul îl cere.

## 3. Look: grade, fundal, vignetă (ce se schimbă între „raw” și „editat”)
- Fundal plat/murdar → `background(clip_ids, mode="color", value="#EEF0F2")` pentru studio curat, sau
  `mode="dim"` pentru un reflector pe persoană, sau `mode="asset"` cu o poză reală a clientului.
- Contrast mai mare, negrii mai adânci, accent cald pe contur: `color_grade(asset, preset="cinematic",
  contrast=1.2, teal_orange=0.5)`.
- Vignetă + bloom: `clip_nodes` cu `vignette` și `glow(threshold 0.8, intensity 0.4)`, sau `clip_fx(effects="vignette")`.
  Pe alb: gradient radial discret (centru #EEF0F2 → margini #B9BCC0), nu negru.
- Subiectul rămâne ÎNTOTDEAUNA cel mai luminos element al cadrului după cuvântul uriaș.

## 4. Mișcare și ritm
- **Fără fade.** Intrările sunt blur → clar (20-30 px → 0, 6-10 cadre la 30 fps), scală 0,9 → 1,0 sau
  slide scurt de 40-80 px cu ease-out expo. Ieșirile sunt mai scurte (0,15-0,25 s) decât intrările.
- **Overshoot** doar pe obiecte „fizice” (carduri, baloane): 4-8%, revin în 0,25 s. Pe text mare: zero overshoot.
- **Anticipare:** un cadru-doi de mișcare invers sau un whip înainte de lovitură.
- **Motion blur** pe orice mișcare rapidă (`clip_keyframes(..., motion_blur=true)`).
- **Scenă nouă la 1,8-3 s.** Dacă vorbitorul are 5 s fără schimbare: punch-in `clip_keyframes` (zoom 1.0 → 1.18,
  0,25 s expo) sau tăiere pe alt cadru (`auto_pacing`, `zoom_on_words`). Nu schimba ceva doar „ca să se miște”.
- **Liniște după lovitură:** 0,6-1,0 s în care nu se mișcă textul; doar un push-in lent pe persoană.
- Densitate: intro (0-10 s) 4-6 elemente-lovitură, corp 1 la 4-6 s. Elemente simultane pe ecran: **max 5**
  (cuvânt + 1-2 rânduri + 1-2 carduri). Peste 5, scoate.
- Cuvântul stă pe ecran cât să fie citit de 2 ori: ~0,35 s/cuvânt + 0,7 s; pentru un singur cuvânt uriaș 0,8-1,3 s.

## 5. Sunet (fiecare lovitură are sunetul ei)
| moment | sfx | când | dB |
|---|---|---|---|
| intrarea cuvântului uriaș | `impact` (+ `bass_drop` doar la hook) | exact pe primul cadru în care e lizibil | -9..-12 |
| înainte de lovitură | `whoosh` / `riser` | cu 0,12-0,3 s / 1 s înainte | -14 |
| cuvinte mici, carduri | `pop` / `click` | pe fiecare cuvânt/pagină, max 3 la rând | -16..-18 |
| tranziție cu pixeli | `glitch` | pe tăietură | -12 |
| cifră finală | `ding` | la sfârșitul `stat` | -14 |
- Regula: **un sunet = o mișcare**. Dacă `sfx_auto` pune sunete peste lucruri mici, scoate-le (`sfx_remove`).
- Muzică: duck pe voce. Sfx-urile stau sub voce (vezi dB din tabel). Tăcerea > 1,5 s în reel = pare înghețat.
- Fără același sunet de 3 ori consecutiv (variantele vin din bibliotecă, dar alternează tipul).

## 6. Slop tells în editare video (dacă faci oricare, refaci)
1. **Subtitrări peste tot și atât.** Un reel cu doar subtitrări word-pop și zero scene = slop. Subtitrările sunt
   baza, nu montajul.
2. **Fade-in/fade-out pe tot textul** sau „typewriter” pe titluri. Intrările sunt blur → clar.
3. **Același efect la fiecare tăietură** (zoom alternant, aceeași tranziție, același whoosh).
4. **Zoom sacadat alternant** pe un vorbitor calm; zoom-ul de punch-in pe fiecare propoziție.
5. **Text mare fără motiv în ce se spune**; cuvinte uriașe care nu sunt cuvântul-lovitură.
6. **Două cuvinte uriașe sau 4 fonturi pe același cadru**; text mic ilizibil pe telefon (<2,5% din înălțime).
7. **Text peste față/gură**; text care acoperă subtitrările.
8. **Emoji, iconițe decorative, stickere** puse ca umplutură.
9. **Gradient violet-albastru neon, glassmorphism, „glow” pe tot** (look de template AI). Glow doar pe UN element
   per scenă, în culoarea accentului din cadru.
10. **Sunet pe tot / sunet deloc.** SFX pe fiecare cuvânt = obositor; zero SFX = „ieftin”.
11. **Tranziții de tip „stea”/cub/pagină** din pachete implicite.
12. **Mișcare fără ease** (liniară), sau cu overshoot pe tot (rubber). Ease-out expo e implicitul.
13. **Grade identic cu raw-ul** când fundalul e plat și murdar: nu există „look” fără grade și fundal curat.
14. **Cifre/dovezi/capturi inventate.** Fără ele, nu pui `stat`, `float_cards`, `day_counter`.
15. **Montaj fără pauze:** 0 secunde de liniște după lovitură; ochiul nu are unde să se odihnească.
16. **Copierea unui creator cadru cu cadru** (logo, panouri, text identic). Folosești tehnica, nu lucrarea.

## 7. Verificare înainte de predare
1. `motion_preview` pe fiecare bloc `behind`: masca, lizibilitate, acoperire 15-35%.
2. `render(preview=true)` apoi `frames_look` la 3-4 momente-lovitură + 1 moment calm.
3. Numără: elemente simultane ≤ 5? Un singur cuvânt uriaș pe cadru? Fiecare lovitură are sunet?
4. Reel-ul se înțelege cu sunetul oprit? (textul poartă ideea) și cu textul ascuns? (vocea poartă ideea).
5. `qa_check`.

## Din referințele neanalizate adânc
Porsche GT3 (tăieturi pe beat, RGB split) și Will Schafer (documentar cinematic): folosește `beats_detect` +
`beat_montage` și `clip_fx(effects="glitch")` pe un cadru; neanalizate cadru cu cadru în această rundă.
