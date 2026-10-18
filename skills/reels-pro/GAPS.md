# GAPS: ce trebuie schimbat în skill-urile vechi și ce lipsește din motor

**Stare (18 oct 2026):** implementate: (b)#1 `background(mode="studio")` (gradient, vignetă, umbră de contact sub
linia picioarelor din mască) și `silhouette` (#11); (b)#2 `background(scale, x, y, move)`; (b)#9
`transition_set(type="invertwhip")` (+ `chromawhip`). Blocurile din plan există toate, cu `behind=true` și strat de
prim-plan (`.fg`). Skill-urile vechi: vezi commit-ul cu motion-design / motion-graphics. Runda 2 (tot 18 oct): #3 `scene_card`, #4 `orbit_words layout="fly"`, #15 `captions_look("registers")`,
plus decupaj RVM, `reel_check`, `reel_plan`, `timeline_frame`, sunet pe lovitura blocurilor. Deschise: #5-#8, #10, #12-#14.

Citit de agentul principal. (a) texte din `motion-design` / `motion-graphics` care duc la slop, cu propuneri;
(b) tehnici din referințe imposibile cu motorul + API-ul din plan, ordonate după impact.

## (a) Skill-urile vechi → slop

### motion-design/SKILL.md
1. **„Un short de 30-60 s are 2-5 blocuri în total”** (secț. 3). Referințele au 6 scene în 14 s de edited (un element-lovitură
   la ~2,3 s). 2-5 blocuri în 60 s produce „subtitrări + 3 titluri” = exact slopul pe care îl reclamă Luca.
   Înlocuiește cu: „Reels/shorts cu vorbitor: o scenă-lovitură la 2-3 s în intro (0-10 s), apoi la 4-6 s; talking head fără
   grafică >6 s doar dacă zoom/tăietură schimbă cadrul. Video lung (>3 min): regula veche rămâne.”
2. **Tabelul „stilul” cere un stil per client și un tabel de blocuri „pe cuvântul care le justifică”**, dar nu spune nimic despre
   registre, ierarhie sau cuvânt uriaș. Adaugă un paragraf „Ierarhia” (3 registre, raport 1 : 4 : 1,7, un singur cuvânt uriaș pe
   cadru) și trimitere către `reels-pro`. Fără asta, `headline` + `kinetic` = același titlu centrat la fiecare 5 s.
3. **„Un singur bloc pe ecran”** (secț. 3). Referințele au 3-5 elemente simultane care se compun (cuvânt + 2 rânduri + carduri).
   Schimbă în: „Un singur *cuvânt uriaș* pe ecran; în jurul lui max 4 elemente mici, fiecare cu rol distinct.”
4. **„Intrare: fade-ul din blur cuvânt cu cuvânt” e prezentată ca stil `iman` pentru TOȚI.** E ok pentru text mic; pe cuvântul
   uriaș cere blur mare + scală + ease expo (0,3 s) și, la hook, `behind=true`.
5. **„Lasă fața liberă” (secț. 3)** interzice implicit text în spatele persoanei. Reformulare: „Fața liberă; textul mare
   merge deasupra/în spatele capului (`behind=true`), niciodată peste ochi/gură.”
6. **Secț. 6 „Ce NU faci”** nu are nimic despre sunet-per-mișcare, culori per scenă sau pauză după lovitură. Adaugă 3 puncte din
   `reels-pro` §4-§6.
7. **Sunetul (secț. 4): „whoosh pe intrarea unui headline”** pe toate = monoton. Cere varianta pe lovitură: impact pe
   cuvântul uriaș, pop pe cuvinte mici, glitch pe pixel_wipe, tăcere pe scene liniștite.
8. **Referințele „Hormozi/MrBeast” fără bază.** Stilurile `hormozi`/`mrbeast` apar în `style_recipe` fără avertisment că sunt
   look-uri foarte copiate; adaugă o linie „nu folosi pentru brand premium, preferă `reel` / `iman`.”

### motion-graphics/SKILL.md
1. **`graphic_add` cu ASS e prezentat ca alternativă de rezervă dar rămâne prima opțiune în tabel** (title_card, kinetic, list,
   counter). Pe reels produce text fără blur, fără ease expo: arată ieftin. Mută secțiunea sub „doar fără Chromium”
   și scoate `kinetic`/`title_card` din recomandările pentru reels.
2. **„Text în spatele persoanei (`behind=True` pe title_card / kinetic…) … o dată, maxim de două ori pe clip”.** Corect ca
   avertisment, dar actualizează cu `motion_add(..., behind=true)` și `stack_title`; limitele (1-2 ori) se păstrează.
3. **Tabelul de durate pentru `title_card` 1,5-3 s și `cta` 2-4 s** nu spune cât stă CUVÂNTUL uriaș (0,8-1,3 s) sau când iese.
   Adaugă „text mare iese în 0,2 s; nu lăsa 3 s fără mișcare”.
4. **„`sfx_auto()` după tranziții și grafice”** pune sfx-uri pe orice. Adaugă: după `sfx_auto`, ascultă/numără; un sfx = o
   mișcare, scoate-le pe cele de pe elemente mici (`sfx_remove`), păstrează impact pe cuvânt uriaș.
5. **`clip_fx`: „`shake`, `glitch`, `flash` pe impact”** fără limită de număr. Adaugă: max 1 flash și 1 glitch la 10 s; glitch doar
   în conținut tech.
6. **„Densitate: un short de 30-60 s = 2-5 grafice”**: aceeași problemă ca la motion-design #1.
7. **Efecte „vignette, grain, sharpen: finisaj discret”** — corect, dar fără grade/relight nu există look; trimite la `reels-pro` §3.

### Alte skill-uri
- `edit-brief`: adaugă întrebarea „reel cu scene-lovitură sau video lung?” și, dacă reel, încarcă `reels-pro` imediat după
  `video-editor-core`.
- `video-editor-core`: la „Ce faci mereu” adaugă „numără elementele simultane și cuvintele uriașe înainte de predare”.
- Descrierea din `skills/motion-design/SKILL.md` nu pomenește „reels”; `reels-pro` trebuie să fie în lista de skill-uri citite.

## (b) Tehnici din referințe care NU se pot face (după impact)

Notă de nume: în plan apare `bg_replace`; în `mcp_server.py` tool-ul se numește `background(mode=...)` (blur, bw, dim, color,
asset, none). SKILL.md folosește `background`.

| # | Lipsă | Unde se vede | Impact | Implementare propusă |
|---|---|---|---|---|
| 1 | **Relight / „studio” în jurul persoanei decupate**: gradient radial în fundal, umbră de contact și reflexie pe podea, rim light, vignetă pe alb | DeC (Scripts/sell), DeZ (studio maro) | Foarte mare: diferența „video cu text” vs „scenă” | `background(mode="studio", value="#EEF0F2")`: masca MODNet + (a) gradient radial în culoarea dată, (b) elipsă de umbră moale sub picioare (blur 40 px, 25% negru, sub masca jos), (c) opțional reflexie (flip vertical al măștii, fade 0→20%). Totul în `render.py` la nivel de compoziție, deterministic. |
| 2 | **Persoană micșorată / mutată pe parcursul unei scene** (35-45% din înălțime, jos), cu ease și blur | DeC (4 din 6 scene), DeZ (sală) | Mare: fără asta nu e loc pentru text mare + carduri | Extinde `clip_keyframes`: permite `zoom` < 1 când fundalul e plin (după `background`), cu `cx,cy` ca ancoră. Randare: scalare persoană + fundal curat. Alternativ parametru `subject_scale`/`subject_y` pe `motion_add` care mută doar persoana în blocurile cu `behind`. |
| 3 | **Scena veche devine card în scena nouă** (picture-in-picture animat) | DeC (4→5), DdG | Mediu-mare | Bloc `scene_card`: ia un cadru/segment randat din montaj (`at`, `duration`) ca imagine și îl animă ca `float_cards` (înclinat, umbră). Prima versiune: cadru static capturat cu `thumbnail_export`. |
| 4 | **Cuvânt/obiect orbitând în perspectivă 3D, cu blur motion lateral, trecând pe lângă cameră** | DeZ (sala de scaune), „We” 3D rotit | Mare | `orbit_words` cu `layout="fly"`: transform CSS 3D (perspective 600px, rotateY/Z), `filter: blur()` proporțional cu viteza (derivata poziției), path Bézier. GSAP + `motion-blur` prin rendering de 4 sub-cadre amestecate. |
| 5 | **Text 3D extrudat / pe podea cu material (cupru), cu reflexie** | DeZ (stop ghosting clients) | Mediu | Randare în Chromium cu CSS `text-shadow` stivuit (12-16 straturi) pentru extrudare + `transform: rotateX(70deg)`; materialul = gradient + `mix-blend-mode`. Evită WebGL (nedeterminist). |
| 6 | **Schimbare de culoare a accentului pe parcursul unui bloc** (roșu → albastru, verde → lime) | DdG | Mediu | Param `accent_to` + `accent_at` în `stack_title`/`bubble`: tween `--accent` în GSAP. |
| 7 | **Wipe cu muchie luminoasă (glow edge) pe text** (CONSISTENCY scris stânga → dreapta) | DeZ | Mediu | `reveal="mask"` cu muchie `linear-gradient` + `filter: drop-shadow(0 0 12px accent)`; durata `reveal_dur`. Probabil deja în plan; confirmă în blocul `stack_title`. |
| 8 | **Widget-uri UI (player muzical, „Performance 48°”, avatare care orbitează)** | DdG | Mic (portofoliu, nu client) | Nu implementa acum. Dacă vine cerere, `bubble` ar putea primi `variant="widget"`. |
| 9 | **Tranziție prin cadru negru INVERTIT + whip cu blur 1 cadru** | DeC (9.875, 14.625), DeZ (12.25) | Mare, ieftin | `transition_set(type="invertwhip", duration=0.1)` în `render.py`: `negate` + `tblend`/xfade `hblur` pe 2-3 cadre. Pune-l între primele 5 tranziții. |
| 10 | **Cadre cu raze de lumină / benzi diagonale animate în fundal** | DeC (oliv) | Mic-mediu | Bloc `light_rays` (benzi gradient diagonale, opacity 6-12%, mișcare lentă) — cu `behind=true`. Alternativ `light_leak` existent, cu `angle`. |
| 11 | **Siluetă threshold (negru pe alb) a persoanei** | DeZ (8.75-12.2) | Mediu | `background(mode="silhouette", value="#FFFFFF")`: masca ca negru plin, fundal culoare. Se poate și cu `clip_nodes` (color exposure -20 → luma_mask), dar nu e fiabil pe păr. |
| 12 | **Generare de decor (sală de scaune, studio, calendar fizic, bancnote)** | DeZ | Mic (cere generare AI plătită) | NU se implementează în motor. `broll_generate`/`broll_stock` + `background(mode="asset")` acoperă o parte. |
| 13 | **Orbi/bokeh luminoși care zboară (particule)** | DeZ (2.4-2.6), DeC | Mic | Bloc `particles` (6-12 cercuri alb-glow, traiectorii Bézier). Folosește rar. |
| 14 | **Retime pe beat (tăieturi pe beat, RGB split) pentru car edits** | Dd6peYGIFjr | Mediu | Există `beat_montage` + `clip_fx glitch`; lipsește RGB split ca efect propriu (`clip_fx` `rgbsplit`, 3-6 px, 4 cadre pe beat). |
| 15 | **Tratarea cuvintelor în caption + motion**: subtitrare în stilul „registre” (cuvânt-cheie condensat roșu, restul sans mic) | DeZ (CONSISTENCY is what compounds) | Mare | `captions_look(look="registers")`: cuvintele din `captions_emphasis` devin `word` condensat accent; restul `sans` mic. Reutilizează registrele din `stack_title`. |

### Top 5 recomandat pentru implementare
1. #1 relight/studio pe persoana decupată.
2. #2 persoana micșorată/mutată cu ease.
3. #9 tranziție prin negru invertit + whip.
4. #4 text zburat în perspectivă cu blur motion.
5. #15 subtitrări în registre (cuvânt-cheie ca `word`).
