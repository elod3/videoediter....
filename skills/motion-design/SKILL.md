---
name: motion-design
description: Direcția de motion graphics, cu gust - alege stilul (Iman Gadzhi, Hormozi, Ali Abdaal, Johnny Harris, minimal, firmă locală), culorile din filmare, blocurile potrivite (titlu, cifră, listă, comparație, capitol, grafic, citat, notificare, poză, CTA, pași), momentul exact din transcript, densitatea și sunetul. Folosește-l când clientul cere „să arate profesional / scump / ca la X”, „pune grafice”, „animații”, „motion”, „text animat”, sau la orice video educațional, de business sau de brand.
---

# Motion design

Motion graphics bune nu înseamnă multe. Înseamnă **puține, la momentul exact, toate din aceeași familie**.
Un spectator nu trebuie să observe animația; trebuie să înțeleagă mai repede și să țină minte ideea.

## 1. Stilul (o dată pe proiect)

`motion_blocks(project)` arată blocurile și stilurile. Alege stilul după client, nu după ce e la modă:

| stil | pentru | ce îl face să arate așa |
|---|---|---|
| `iman` | business, agenții, coaching premium, personal brand „scump” | text din blur cuvânt cu cuvânt, culori din filmare 60/30/10, easing moale, grilă la capitole |
| `hormozi` | vânzări, educație de business directă, energie | majuscule groase condensate, galben + alb, pop scurt, cifre mari |
| `abdaal` | educație, productivitate, profesori, cursuri | panouri deschise, marker galben ca pe hârtie, ton prietenos |
| `harris` | povestea firmei, documentar, explicații cu date | serif de presă, culori de hârtie veche, accent roșu, ritm lent, grain |
| `minimal` | creatori personali, idei, branduri liniștite | alb-negru, serif, o singură idee pe ecran, aproape fără accent |
| `local` | service, clinică, construcții, restaurant, imobiliare | clar, de încredere, accentul = culoarea brandului, cifre și pași concreți |

Dacă clientul cere un look complet cunoscut (subtitrări + punch-in + sfx), pornește cu `style_recipe`
(hormozi, mrbeast, tiktok, podcast, cinematic) și apoi pune stilul de blocuri potrivit.

Apoi `motion_style(project, style="iman", palette="auto")`: accentul vine din filmare (culoarea dominantă),
fundalurile sunt aceeași nuanță foarte închisă. Dacă clientul are culoare de brand, pune-o în brand
(`brand_captions(highlight=...)`): are prioritate. Un singur stil pe tot clipul.

## 2. Ce bloc, pe ce moment

Fiecare bloc stă pe **cuvântul care îl justifică** în transcript. Fără motiv în ce se spune, nu pui nimic.

| se spune… | bloc | cum |
|---|---|---|
| ideea clipului, în primele 2-3 s | `headline` | 4-8 cuvinte, 1-2 cuvinte în `highlight`; `position: top` dacă fața e la mijloc |
| o cifră („am ajuns la 12.500 de lei”) | `stat` | pornește pe cifră; `before` dacă se compară cu ceva |
| prima dată apare o persoană | `lower_third` | 3-4 s, în primele 5 s ale ei |
| o enumerare („trei lucruri…”) | `list` | `times` = momentele fiecărui punct, din transcript |
| înainte / după, noi / ei, ieftin / scump | `compare` | `winner` = varianta pe care o recomandă vorbitorul |
| schimbare de subiect într-un clip lung | `chapter` | 2-3 s, pe tot ecranul, cu riser înainte |
| o evoluție în timp, mai multe cifre | `bars` / `line_chart` | maxim 6 valori; cifrele de la client, niciodată inventate |
| o frază memorabilă | `quote` | doar fraza exactă spusă în clip |
| „m-a sunat un client”, „a venit plata” | `notification` | ca dovadă vizuală a poveștii |
| o captură, un produs, un logo, o poză | `image_card` | poza urcată de client (`images={"image": "a3"}`) |
| un proces („cum lucrăm”) | `steps` | 3-4 pași, câte 2-4 cuvinte |
| finalul / îndemnul | `cta` | text = acțiunea reală („Programează-te”, „Abonează-te”) + motivul în `sub` |


**Lipit de un obiect:** `track_point(at, x, y)` pe un punct cu detalii (logo, produs, față), apoi
`motion_add("pin", ..., params={"label": "...", "x": x, "y": y}, track="t0")`. Oprește blocul la `lost_at`.

## 3. Densitate și ritm

- **Intro (primele 10-15 s): mai dens.** 1 bloc la 3-6 s.
- **Corp: rar.** Un short de 30-60 s are 2-5 blocuri în total, un video de 10 min are ~2 pe minut,
  plus capitole. Peste asta, ecranul devine zgomot.
- **Un singur bloc pe ecran.** Nu suprapune un bloc peste altul și nici peste un `graphic_add` vechi.
- **Lasă fața liberă.** Pe vertical, fața stă de obicei în treimea de sus: blocurile merg `center`/`bottom`
  sau, cu fața jos, `top`. Subtitrările stau jos: nu pune blocuri peste ele (sau mută subtitrările mai sus).
- **Durata:** cât să poată fi citit de două ori. Regula: ~0,35 s pe cuvânt + 1 s, între limitele din `motion_blocks`.

## 4. Sunetul (fără el, animația pare ieftină)

Fiecare stil are în `motion_blocks` sunetele lui. Pune-le cu `sfx_add` la începutul blocului:
- `whoosh` pe intrarea unui headline sau a unei scene, `pop` / `click` pe fiecare punct din listă,
  `riser` cu ~1 s înainte de un capitol, `ding` pe finalul unui `stat`.
- -12..-16 dB sub voce. La `minimal` și `harris`: aproape deloc.

## 5. Verificare (obligatoriu, înainte de randarea finală)

1. `motion_preview(project, "m0")` pentru fiecare bloc; uită-te la imagine:
   - se citește pe telefon? (imaginea e mică: dacă tu o citești greu, și omul la fel)
   - acoperă fața sau subtitrările?
   - textul e cel spus în clip, fără greșeli și cu diacritice?
   - culorile se potrivesc cu filmarea?
2. `render(preview=true)` → `frames_look` pe 2-3 momente cu blocuri.
3. Dacă un bloc nu ajută înțelegerea, scoate-l (`motion_remove`). Mai puțin e aproape mereu mai bine.

## 6. Ce NU faci

- Blocuri „ca să fie ceva pe ecran”, emoji, iconițe decorative.
- Cifre, rezultate, citate sau recenzii inventate. Dacă clientul n-a spus cifra, nu există `stat`.
- Același bloc de 5 ori la rând; amestecul de stiluri în același clip.
- Text lung: un bloc spune o idee, nu un paragraf.
- Să copiezi un creator exact. Stilul e o direcție; clientul are vocea lui.

## Ce poți urmări la creatorii de referință

Când clientul dă un exemplu, analizează-l cu `reference_analyze`, apoi alege stilul cel mai apropiat:
- **Iman Gadzhi:** cât de rar apar animațiile în corp față de intro; cum culoarea graficelor vine din cadru.
- **Alex Hormozi:** subtitrări de 2-4 cuvinte, cuvântul spus colorat, tăieturi la 1-3 s.
- **Ali Abdaal:** cuvinte-cheie marcate, ritm de 2-5 s pe cadru, tăieturi la pauzele de gând.
- **Johnny Harris / Vox:** poze care alunecă încet, cu blur ușor; date și hărți ca dovezi.
- **Dan Koe / Matt D'Avella:** spațiu gol, o idee pe ecran, aproape fără efecte.
- **MrBeast:** din 2024 merge pe ritm mai lent și mai multă profunzime spre final, nu pe tăieturi continue.
