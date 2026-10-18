---
name: cinematic-story
description: Vlog / documentar scurt cinematic cu poveste (hook, setup, problemă, proces, payoff) în stilul Will Schafer, Casey Neistat, Peter McKinnon - „show don't tell", B-roll de proces filmat ca reclamă, umor vizual, subtitrare mică și discretă, grafică rară dar memorabilă, sound design și o tăcere înaintea payoff-ului. Folosește când clientul zice „vlog cinematic”, „documentar scurt”, „storytelling”, „povestea proiectului / a brandului / a produsului”, „ca în clipul ăsta” pe un video narat cu B-roll, sau când un talking head cu B-roll iese plat.
---

# Poveste cinematică (vlog / documentar scurt)

Un vlog bun nu e un om care vorbește cu poze peste el. E **o poveste în care fiecare propoziție importantă are un cadru
care o arată** și în care sunetul și tăcerea poartă emoția. Analiză cadru cu cadru în
`references/breakdown-Dac8t7RhJ3b.md` (101 s, Will Schafer). Ce nu se poate încă: `../beat-montage/GAPS.md`.

## 0. Principii (din referință + surse)

1. **Show, don't tell.** Orice substantiv concret din voce („Raspberry Pi”, „cablu HDMI”, „carduri”) apare în cadru în
   momentul rostirii. Glumele sunt vizuale: „caut un TV vechi” -> tăiere la un tablou de bord de mașină.
2. **Hook în 3 s:** o propoziție provocatoare + un cadru neobișnuit. Nu te prezenta. (Referința: ecran negru + propoziția
   cu text mic, apoi whip pe rafturi.)
3. **Structură:** hook (0-10%) -> setup / cine e și ce vrea (10-30%) -> problema numită clar (30-40%) ->
   proces în pași cu B-roll (40-75%) -> payoff (75-85%) -> sens emoțional (85-95%) -> buton final.
4. **Ritm pe secțiuni, nu uniform:** colaj rapid în hook (1 tăietură / 1-1.5 s), vorbitor la cameră cu jump-cut
   (1 tăietură / 1.2 s) în explicații, procesul pe ritmul vorbirii (obiect nou la fiecare cuvânt-cheie), payoff **lung și
   liniștit** (5-12 s într-un cadru larg).
5. **Tăcerea e un instrument:** înainte de payoff scoate muzica și vocea 2-3 s (în referință, nivel -29 dB față de -17 normal).
6. **Un singur limbaj grafic:** o culoare de accent (verde neon pentru „date” / roșu pentru subtitrări în insert) și 2-3 tipuri
   de grafică. Repetă-le.
7. **Prima-persoană** la cameră înseamnă contact vizual: camera la nivelul ochilor, lumină de tip „cameră întunecată cu un
   ochi de lumină caldă” (look scump, nu studio).

## 1. Brief și plan (înainte să tai)

1. `edit-brief` apoi `asset_list`, `media_analyze`, `transcript_get(asset)` pe tot materialul vorbit.
2. Scrie schema narativă ca listă `[timp ~ | funcție | propoziția din transcript | ce se vede]`. Fiecare propoziție-cheie
   are cadru; cele fără cadru rămân pe vorbitor.
3. Lista de B-roll cerut (pentru client / pentru stock): cadre „de produs” pentru fiecare obiect numit, macro-uri
   (mâini, ochi, LED, buton), un cadru larg „reveal”, un cadru „emoție” (omul reacționează).

## 2. Tăieturi pe voce

- `clean_speech(asset)` apoi `cut_silences(asset, min_silence=0.35, padding=0.06)`. Ritmul nu e rapid-rapid: păstrează o
  respirație înainte de propoziția emoțională (nu o tăia).
- Tăieturi de tip jump-cut pe explicații: `auto_pacing(max_static=3.0, zoom=1.12)` (alternează planul normal și punch-in).
- Primul cadru = hook: dacă cea mai bună propoziție e mai târziu, `hook_teaser(start, end, text="")` sau `clip_move`.
- Pe emoție nu pune B-roll: lasă fața (și nu tăia respirația).

## 3. B-roll de proces („show”)

1. `broll_add(asset, at, duration, src_in, mode="full")` pe fiecare obiect numit, la momentul cuvântului: ia `at` din timpul
   cuvântului din `transcript_get` (timp de timeline, după tăieturi). Vocea de pe V1 continuă = L-cut natural.
2. Obiecte enumerate („un Raspberry Pi, un cablu, un card, un stick”): un B-roll scurt (0.6-1.2 s) per obiect, la cuvântul lui,
   toate din aceeași poziție de cameră (masă, fundal întunecat) ca să pară același cadru care se umple. Alternativ pentru
   poze/fișiere statice: `visuals_fill(assets="a3,a4,a5", at_words="w12,w15,w18", kenburns=true)`.
3. Cadre de proces: macro cu rack focus, mâini, POV, top-down pe masă; `zoom_animate(clip, 1.1)` lent pe cele statice.
4. **J-cut:** pune B-roll-ul la începutul clipului de voce următor (imaginea nouă apare 0.3-0.6 s după ce începe vocea).
   **L-cut:** B-roll-ul acoperă finalul clipului care vorbește. Nu tăia vocea; sunetul curge continuu pe V1.
5. Glume vizuale: un cadru de 1-1.5 s care contrazice sau exagerează propoziția (tablou de bord în loc de TV vechi),
   pus exact pe cuvânt, nu înainte.
6. Ecran / aplicație din B-roll: `frame="laptop"` sau `"phone"`. Detaliu peste vorbitor: `frame="rounded", pip_pos="tr"`.
7. Fără footage: `broll_stock(query, count)` (engleză, concret), `frames_look` înainte de folosire. Spune în raport sursa.

## 4. Încadrare (letterbox în vertical)

- Referința e 16:9 în cadru vertical: bandă de imagine pe mijloc, negru sus și jos, subtitrare în bandă.
  `timeline_format(fmt="9:16", fill="pad")` pune sursa 16:9 în cadru cu bare negre.
- Subtitrările mici stau pe imagine, centrate, 1.5-3% din înălțime, albe (negre pe fundal alb).
- Pentru 16:9 pur: `timeline_format(fmt="16:9")`.

## 5. Subtitrări discrete (nu „Hormozi”)

- `captions_add(asset, style="classic_bottom")` apoi `captions_look(engine="motion", look="line", y=0.55)`: cuvintele apar
  cu blur, un rând, mici, centrate pe corp / jos. Fără karaoke, fără culori pe cuvinte (doar 1-2 cuvinte cheie pe minut cu
  `captions_emphasis(words="plan", scale=1.2)`).
- Un cuvânt-cheie poate ieși mare (ex. „plan.” la „so this is the plan”): `graphic_add(kind="kinetic", text=..., ...)`, o dată
  la 30-40 s.
- Pe inserturi (cerc, carduri albe): subtitrarea își schimbă culoarea (roșu pe negru / negru pe alb). Se face cu `brand_captions` sau
  `captions_look`, o singură variantă pe tot videoul; restul schimbărilor: după GAPS.

## 6. Grafică (rară și sistematică)

| Moment | Tool |
|---|---|
| Titlul planului / proiectului (carte de titlu pe cadru de proces) | `graphic_add("title_card", ...)` sau `motion_add("headline", ...)` |
| Cuvânt-cheie mare pe voce („INFLUENCED”) | `motion_add("kinetic"...)` / `graphic_add("kinetic", behind=true)` (în spatele persoanei) |
| Etichetă urmărită pe obiect („$13.49”, „READ BOOKS”) | `track_point` + `motion_add("pin", track="t0")` cu `motion_style(palette="#39FF14")`; contur / cutie: după GAPS (1.8) |
| Carduri cu poze (obiecte personale pe fundal alb) | `motion_add("image_card", images={"image":"a5"})` per obiect, pe cuvântul lui |
| Insert rotund fisheye | după GAPS (1.6); până atunci `broll_add(frame="rounded")` |
| Linii de viteză în spatele persoanei decupate | `motion_add("speed_lines", behind=true)` (bloc nou; dacă `motion_blocks` nu-l arată: după GAPS) |
| Capitole | `chapters_set` doar la video > 3 min |
| Final | `graphic_add("cta")` sau text mic; nu o cartelă mare |

Cel mult 6-10 elemente grafice în 100 s. Fiecare declanșat de un cuvânt, nu de timp. `motion_preview` înainte de randare.
Stil: `motion_style("reel")` (contrast, accent) sau `minimal` pentru ton calm.

## 7. Culoare și lumină

- `color_grade(asset="all", preset="cinematic")` apoi ajustezi: `contrast=1.15`, `saturation=0.9`, umbre ușor reci; păstrează o
  singură sursă caldă în cadru (lampă, neon, TV).
- `color_match` cu referința clientului dacă există.
- Talking head cu fundal dezordonat: `background(clip_ids, mode="dim")` (fundal întunecat, persoana luminată).
- `style_recipe("cinematic")` dă o bază, dar pune subtitrări „classic_bottom”: schimbă-le după cu secțiunea 5.

## 8. Sunet (jumătate din „cinematic”)

1. Voce curată: `audio_clean(asset, preset="medium")`; `audio_check` pentru nivel (țintă ~ -14 LUFS integrat pentru social; referința: -14.2).
2. Muzică sub voce: `music_set(asset, volume_db=-20, duck=true)` (piesă lentă, fără voce). `music_find(mood="cinematic, ambient")` dacă nu are clientul.
3. **Hush înainte de payoff:** `music_set` nu are automatizare: împarte fișierul de muzică / sau scoate muzica 2 s cu un clip de
   tăcere pe timeline; alternativ taie vocea 2-3 s (`range_remove` pe o pauză) și lasă doar `sfx_add("riser")` -> `sfx_add("impact")`
   exact când apare cadrul larg. Nu fă hush fără payoff.
4. `sfx_add("whoosh", at=<tăietura>)` la whip-uri și la elementele grafice care intră; `pop` la etichete; `click` la apăsări (buton TV);
   `impact` la titlul planului; `ding` la „completat”. Nivel -12 .. -16 dB sub voce. `sfx_auto` pune baza, apoi ștergi ce e prea mult.
5. Sunet ambiental / foley: B-roll-ul de pe V2 nu aduce sunetul lui (nu am găsit amestec audio pentru B-roll în `render.py`; verifică cu `audio_check` pe render). Pune
   `sfx_add("click")` la apăsări, `sfx_add("swipe")` la mișcări de mână, `sfx_add("camera")` la un cadru foto; sau urcă un
   asset audio de foley (`sfx_add(<id asset audio>, at)`). Nu lăsa B-roll-ul de proces complet mut sub o singură voce.
6. Final: ultimul cadru larg ține 5-10 s doar cu muzica urcată (`music_set(volume_db=-12)` pe ultima secțiune; dacă nu poți automatiza, alege
   piesa cu final plin și taie vocea înainte).

## 9. Tranziții

- Hook: `transition_set(clip, "whipleft", 0.2)` pe prima trecere de la text la B-roll; colajul de obiecte pe tăieturi dure.
- Între secțiuni (setup -> problemă -> proces): `fadeblack` 0.4 s sau o tăietură pe sunet (whoosh + cadru nou).
- Alb <-> negru (pagini albe de grafică între scene întunecate): `transition_set("fadewhite", 0.15)` pe intrare, tăiere dură pe ieșire.
- Match-cut de emoție (adult -> copil în același cadru): tăietură dură, aceeași compoziție; nu pune tranziție.

## 10. Verificare

1. `render(preview=true)` -> `frames_look(asset="render:preview", cols=6, rows=5)`; verifică: densitatea tăieturilor pe secțiuni
   (hook rapid, proces la ritmul vocii, payoff lung), fiecare obiect numit vizibil, subtitrări citibile (contrast pe alb / pe imagine luminoasă).
2. `style_compare` dacă există referință.
3. `qa_check` pe final (nivel de voce, tăcere accidentală).
4. În raport: ce vine din materialul clientului, ce din stock, ce lipsește (cadrele pe care i le ceri pentru versiunea 2).

## Nu face

- Nu acoperi cu B-roll fraza emoțională sau fața în momentul de adevăr.
- Nu schimba stilul subtitrărilor / grafic de la o secțiune la alta fără motiv.
- Nu pune muzică puternică în timpul explicațiilor; nu pune sfx pe fiecare tăietură.
- Nu pune 10 obiecte în 3 s: fiecare obiect = cuvântul lui, minim 0.6 s.
- Nu promite inserturi circulare fisheye, etichete cu contur sau split edits reale până nu sunt în GAPS implementate.
