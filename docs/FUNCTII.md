# Tot ce știe vedit

Lista completă, luată din cod. Fiecare funcție are între paranteze numele tool-ului pe care îl folosește
agentul; tu nu trebuie să-l știi, doar ceri în cuvintele tale. Unde e util, e dat și un exemplu de cerere.

Pe scurt: **89 de tool-uri de editare**, **16 skill-uri** (instrucțiunile de editor ale agentului), **site cu
conturi și plăți** și **3 moduri de a rula agentul**.

---

## 1. Tăieturi și curățare

| Funcție | Ce face | Exemplu de cerere |
|---|---|---|
| Tăierea pauzelor (`cut_silences`) | scoate liniștile, cu ritm reglabil (TikTok agresiv / YouTube / podcast) | „taie pauzele” |
| „ăăă” și bâlbe (`clean_speech`) | scoate automat „ăăă, hmm, um” și repetițiile („eu eu cred”), în ro / en / hu | „scoate ăăă-urile și bâlbele” |
| Tăiere pe cuvinte (`cut_words`) | taie exact cuvintele / frazele alese din transcript, ca în Descript | „scoate fraza cu «stai, am greșit»” |
| Doar anumite fragmente (`keep_words`) | construiește clipul numai din bucățile alese, în ordinea dorită | „păstrează doar povestea de la minutul 3” |
| Scoate un vorbitor (`cut_speaker`) | taie sau păstrează doar ce spune o persoană | „scoate întrebările moderatorului” |
| Ritm automat (`auto_pacing`) | niciun cadru static prea lung: jump cut-uri pe final de cuvânt, cu punch-in | „fă-l mai dinamic” |
| Tăiere pe interval (`range_remove`) | scoate un interval de timp | „taie de la 0:40 la 0:52” |
| Clipuri pe timeline (`clip_add`, `clip_remove`, `clip_move`, `clip_trim`) | adaugă, șterge, mută, scurtează | „mută partea cu prețul la început” |
| Anulează / refă (`undo`, `redo`) | orice pas, al tău sau al agentului; refă merge până la următoarea editare | „anulează ultimul pas” |

## 2. Format și încadrare

| Funcție | Ce face |
|---|---|
| Formate (`timeline_format`) | 9:16, 16:9, 1:1, 4:5; umplere crop, pad (benzi) sau blur (fundal încețoșat) |
| Încadrare pe față (`auto_reframe`) | urmărește fața la trecerea pe vertical; cu punch-in-uri opționale |
| Încadrare manuală (`reframe`) | centru și zoom pe un clip |
| Cine vorbește (`speakers_detect`) | vorbitorul activ din imagine (gura + sunet), fără token |
| Zoom animat (`zoom_animate`) | push-in / Ken Burns pe clip |
| Punch-in pe cuvinte (`zoom_on_words`) | zoom pe ideea-cheie, exact pe cuvânt |
| Zoom pe ecran (`screen_zoom`) | la înregistrări de ecran: zoom lin pe meniu / buton / tastare, înapoi la ecranul întreg la scroll |

## 3. Subtitrări și text

| Funcție | Ce face |
|---|---|
| Transcriere (`transcript_get`) | whisper local, fiecare cuvânt cu id; limbă detectată automat |
| Subtitrări (`captions_add`) | 5 stiluri: `bold_center`, `karaoke`, `word_pop` (un cuvânt cu pop), `boxed` (casetă TikTok), `classic_bottom` |
| Cuvinte-cheie (`captions_emphasis`) | colorate și mărite automat sau alese de mână (fără nume proprii) |
| Corectură (`transcript_fix`) | „w12=Mihai”; subtitrările se refac singure |
| Editare text subtitrări (`captions_list`, `captions_text`) | vezi și schimbă orice rând (ex. traducere) |
| Text pe ecran (`text_add`) | titluri, hook text, sus / centru / jos |
| Culoare per vorbitor | la podcast, fiecare persoană cu culoarea ei (cu diarizare) |
| Export subtitrări (`captions_export`) | `.srt` și `.vtt` |

## 4. Motion graphics (`graphic_add`, `graphic_remove`)

9 tipuri, animate:
- **`lower_third`**: nume și rol;
- **`title_card`**: titlu mare;
- **`callout`**: săgeată cu etichetă spre un punct;
- **`counter`**: număr care crește („0 → 10.000 lei”);
- **`progress_bar`**: bară de progres;
- **`cta`**: îndemn la final;
- **`list`**: puncte care apar pe rând;
- **`kinetic`**: text kinetic, cuvânt cu cuvânt;
- **`circle`**: cerc de evidențiere.

Opțional, **textul trece prin spatele persoanei** (`behind`).

## 5. Efecte vizuale, viteză, culoare

| Funcție | Ce face |
|---|---|
| Tranziții (`transition_set`) | 18: fade, dissolve, fadeblack, fadewhite, wipe, slide, smooth, circle, radial, zoomin, hblur, pixelize |
| Efecte (`clip_fx`) | 11: alb-negru, vintage, vignetă, blur, sharpen, glitch, shake, flash, grain, oglindă, invert |
| Viteză (`speed_set`, `speed_ramp`) | 0.25x-4x, sunetul își păstrează tonul; speed ramp (încet → repede) |
| Freeze frame (`freeze_frame`) | oprește imaginea pe un cadru |
| Stabilizare (`stabilize`) | pentru filmări din mână |
| Culoare (`color_grade`) | 7 look-uri: cald, rece, contrast, desaturat, alb-negru, cinematic, luminos + reglaje fine |
| Potrivire de culoare (`color_match`, `color_reset`) | ca într-un clip de referință (LUT 3D) |
| Fundal fără green screen (`background`) | persoana decupată: fundal blurat (portret), culoare sau altă poză / clip |
| Green screen (`broll_key`) | scoate fundalul verde de pe B-roll |
| Blur pe fețe (`blur_faces`) | fețele urmărite pe tot clipul, blur sau pixel, opțional fără persoana principală |
| Blur pe zone (`blur_region`, `blur_clear`) | plăcuțe, ecrane, adrese, logo-uri străine |

## 6. Sunet

| Funcție | Ce face |
|---|---|
| Verificare (`audio_check`) | zgomot, clipping, recomandă curățarea potrivită |
| Curățare voce (`audio_clean`) | 4 preseturi: light, medium, strong, voice |
| Muzică (`music_set`) | sub voce, cu ducking automat (scade când vorbești) |
| Volum per clip (`clip_volume`) | |
| Loudness | automat -14 LUFS (TikTok / YouTube / Instagram), verificat la QA |
| Efecte sonore (`sfx_add`, `sfx_auto`, `sfx_remove`) | 9 sintetizate: whoosh, pop, click, impact, riser, ding, swipe, bass drop, bleep; `sfx_auto` le pune singur pe tranziții, grafice și punch-in |
| Cenzură (`censor_words`) | bip ca la TV sau liniște, exact pe cuvânt; listă de înjurături ro / en / hu; „p***” în subtitrări |
| Beat-uri (`beats_detect`) | BPM și beat-urile piesei |

## 7. Voce AI, dublaj, faceless

| Funcție | Ce face |
|---|---|
| Voice-over (`voiceover`) | text → voce, local și gratuit, în 7 limbi: ro, en, hu, de, es, fr, it |
| Vocea ta (`narration_set`) | o înregistrare urcată devine narațiunea |
| Imagini pe voce (`visuals_fill`) | pozele / clipurile se schimbă exact pe cuvântul din script, cu Ken Burns |
| Dublaj (`dub`) | clipul tău în altă limbă, replică cu replică, grăbit automat ca să încapă; subtitrările se refac (fără lip-sync) |
| Audiogram (`audiogram`) | podcast doar audio → video cu poză / culoare, undă animată (undă, bare, linie) și subtitrări; merge și pe un fragment |

## 8. Multicam și podcast

| Funcție | Ce face |
|---|---|
| Sincronizare (`multicam_sync`) | camerele se aliniază după sunet, la milisecundă |
| Camera pe vorbitor (`multicam_auto`) | 3 moduri: după microfonul care aude mai tare, după diarizare, sau în rotație; plan larg la suprapuneri |
| Unghi manual (`multicam_angle`) | „pune camera wide la reacția de la 2:30” |
| Split-screen (`split_screen`) | două camere sus / jos (9:16) sau stânga / dreapta |
| Diarizare (`diarize`) | „cine vorbește când” (pyannote, cere `HF_TOKEN`) |

## 9. Shorts din video lung

| Funcție | Ce face |
|---|---|
| Momente virale (`highlights_find`) | cele mai bune fragmente cu scor (hook, energie, ritm, pauze), fără să citească tot transcriptul |
| Hook teaser (`hook_teaser`) | momentul tare pus și la început, cu flash |
| Rețete de stil (`style_recipe`) | 5 look-uri gata: Hormozi, MrBeast, TikTok, podcast, cinematic |
| Montaj pe beat (`beat_montage`) | clipurile tăiate pe ritmul piesei |

## 10. B-roll

| Funcție | Ce face |
|---|---|
| B-roll propriu (`broll_add`, `broll_remove`) | peste vorbire, pe pista V2, full sau picture-in-picture |
| Stock gratuit (`broll_stock`) | caută și aduce clipuri de pe Pexels (cere `PEXELS_API_KEY`) |
| Generat cu AI (`broll_generate`) | fal.ai / Replicate, **doar cu bifa clientului** (costă bani) |

## 11. Stil de referință

| Funcție | Ce face |
|---|---|
| Analiză (`reference_analyze`) | ritm, format, culoare, subtitrări din clipul de exemplu al clientului |
| Comparare (`style_compare`) | cât de aproape e montajul de referință și ce mai trebuie schimbat |

## 12. Brand

| Funcție | Ce face |
|---|---|
| Logo (`brand_logo`) | colț, mărime, opacitate |
| Culori și font (`brand_captions`) | pentru subtitrări și grafice; font propriu urcat |
| Intro / outro (`brand_intro_outro`) | lipite automat la fiecare export |
| Kit-uri (`brand_kit`) | salvate pe cont, aplicate pe orice proiect; kit-ul „implicit” merge singur pe proiectele noi |
| Resetare (`brand_clear`) | |

## 13. Livrare și verificare

| Funcție | Ce face |
|---|---|
| Preview și final (`render`) | preview rapid 540p (gratuit), final la rezoluție întreagă |
| Preseturi de platformă (`export_preset`) | 7: TikTok, Reels, Shorts, YouTube, feed Instagram, LinkedIn, X, cu formatul și durata maximă a fiecăreia |
| Thumbnail (`thumbnail_export`) | cadru sau stil YouTube: persoana decupată cu contur alb, titlul în spate |
| Capitole YouTube (`chapters_set`) | pentru descriere, opțional și ca titluri în video |
| QA automat (`qa_check`) | durată, rezoluție, loudness, clipping, cadre negre, liniști lungi, plus verificări vizuale (subtitrarea peste față, fața tăiată la margine) |
| Ochii agentului (`frames_look`, `media_analyze`, `timeline_view`) | se uită la cadre, analizează clipul și citește montajul ca text |

## 14. Siguranță

- **Lacăt pe proiect:** agentul unui client nu poate atinge proiectul altui client.
- **Acces la fișiere:** agentul nu citește nimic din afara proiectului.
- **Generare plătită:** merge doar cu bifa clientului; cheile API nu ajung la agent fără ea.
- **Bugete per job:** număr maxim de tool-uri, randări și descărcări; timeout.
- **Conținut extern:** transcriptul, numele de fișiere și metadatele sunt marcate ca date, cu detecție de „prompt injection”.
- **Timeline-uri din API:** nu pot seta căi de fișiere și nu pot strecura filtre ffmpeg (culorile se validează strict).
- **Claude Code** rulează fără Bash, scriere de fișiere sau web.

---

## 15. Site-ul (ce vede clientul)

- **Pagina publică:**
  - prezentare, cum se plătește (credite, minute gratuite la înscriere), cont nou și autentificare;
  - „am uitat parola” cu email (cere SMTP).
- **Proiecte:**
  - încărcare de video, audio și poze;
  - roluri pentru fișiere: principal, referință, B-roll;
  - miniaturi.
- **Editorul, ca un NLE (inspirat din CapCut și Resolve):**
  - **bara de unelte din stânga:** fișiere, editare după text, subtitrări, brand, livrare, Resolve;
  - **monitor live:** redă montajul direct din surse, fără randare (tăieturi, viteză, încadrare, B-roll, muzică, texte);
    tab-urile de lângă el arată fișierele randate;
  - **dreapta:** agentul AI (chat + jurnal numerotat) sau proprietățile selecției, ca în CapCut;
  - **„Cere agentului pentru c3”:** din proprietățile unui clip, căsuța agentului se completează cu clipul și intervalul lui.
- **Editare manuală, fără AI** (pentru schimbări mici, fără să aștepți agentul):
  - taie la playhead (`S` / `⌘B`), scurtează până la playhead (`Q` / `W`), dublează (`⌘D`), șterge (`⌫`), anulează (`⌘Z`), refă (`⇧⌘Z` / `⌘Y`);
  - tragi de marginile clipului (trim cu ripple, lipire de playhead și de margini), muți clipurile prin drag;
  - B-roll, texte și grafice se mută și se întind cu mouse-ul;
  - proprietăți: viteză, volum, încadrare, tranziție, zoom animat, efecte, freeze, format, text nou la playhead;
  - „+ pe timeline” pe un fișier îl pune la final (audio: ca muzică); „șterge” (două clicuri) îl scoate din proiect,
    dacă nu e folosit în montaj;
  - cât lucrează agentul, editările manuale așteaptă (serverul le refuză, ca să nu se suprapună cu ale lui);
  - fiecare schimbare e un pas de undo, iar subtitrările și graficele urmează tăieturile (ripple pe server).
- **Modul de editare** (tasta `E` sau butonul „Editare” din bara din stânga; `⇧4` / `⇧5` / `⇧6` = paginile):
  - **Montaj:** timeline-ul ia aproape tot ecranul, cu toate pistele vizibile și înalte (slider „piste”);
    clip vertical → monitorul stă fix în dreapta; clip orizontal → monitorul e o fereastră plutitoare pe care o muți
    și o redimensionezi (își ține poziția); proprietățile se deschid tot într-o fereastră (`I`);
  - **navigare ca pe o planșă:** `⌘` + rotiță sau pinch = zoom exact sub cursor, rotița / trackpad-ul mută,
    `⌥` + tragere sau rotița apăsată = mâna, **„Tot” (`⇧Z`)** = de la primul clip la ultimul;
    harta de deasupra arată tot timeline-ul cu fereastra vizibilă (o tragi ca să te muți);
    linia de redare trece prin toate pistele și arată timecode-ul; ecran complet din bara de sus,
    dublu-click pe monitor = preview pe tot ecranul;
  - **Noduri (ca Fusion):** graf de efecte pe fiecare clip (`clip_nodes` pentru agent). 22 de noduri: corecție primară,
    roți lift/gamma/gain, curbe, nuanță, blur, claritate, glow, vignetă, granulație, aberație cromatică, pixelare,
    contururi, negativ, oglindă, transformare, fereastră (mască elipsă), mască după lumină, cheie de culoare,
    culoare plină și merge (9 moduri, cu mască). Tragi de pe ieșirea unui nod pe intrarea altuia; Tab / click dreapta
    = adaugă; `1` = vezi ieșirea nodului; viewerul e un cadru randat pe server, exact ca la export;
  - **Culoare (ca Resolve):** roți lift / gamma / gain cu master, corecție primară (expunere, contrast, saturație,
    gamma, temperatură, tentă), curbă, histogramă RGB, „ține: înainte”, „aplică pe toate clipurile”;
    banda de clipuri de jos alege clipul și momentul. Corecția e tot un lanț de noduri, vizibil și în pagina Noduri.
- **DaVinci Resolve, dus-întors** (`vedit/resolve.py`, `integrations/resolve/vedit.lua`):
  - scriptul din Resolve (Workspace › Scripts › vedit, merge și în versiunea gratuită) aduce montajul ca timeline
    și îl trimite înapoi; instalare cu `make resolve-install`;
  - sau manual: `.fcpxml` descărcat din panoul Resolve și încărcat înapoi după File › Export › Timeline › FCPXML;
  - din Resolve vin tăieturile, ordinea, viteza, freeze-ul, tranzițiile și B-roll-ul; încadrarea, efectele, fundalul
    și blur-ul pe fețe rămân din vedit.
- **Timeline vizual:**
  - piste TEXT, GFX, V2 (B-roll), V1, SUB, A2 (muzică), A3 (voce), SFX; zoom cu sliderul sau pinch;
  - miniaturi pe clipuri, insigne pentru tranziție, zoom, freeze și efecte.
- **Joburi în timp real:** pași live, cu anulare și „resetează agentul”.
- **Conturi și bani:**
  - credite: 1 credit = 1 minut exportat; preview-urile sunt gratuite;
  - pachete cumpărate prin Stripe Checkout;
  - istoricul creditelor;
  - plafoane anti-abuz.
- **Administrare (`vedit-admin`):** lista de conturi, credite adăugate sau scăzute, parolă temporară.

## 16. Cum rulează agentul

| Mod | Pentru cine |
|---|---|
| `claude-code` | tu: folosește abonamentul tău Claude, local |
| `llm` | clienții: orice API compatibil OpenAI (OpenRouter, Groq, Ollama local...), cu sau fără vedere |
| `scripted` | fără AI: înțelege cereri simple (pauze, bâlbe, 9:16, subtitrări, multicam, audiogram, cenzură, blur, zoom pe ecran, muzică, B-roll) |

## 17. Pentru tine ca dezvoltator

- `make demo`: material de test (vlog, podcast cu 3 camere, audio podcast, înregistrare de ecran, piesă, B-roll, poze);
- `make test`: 194 de teste care randează video real;
- `vedit <tool> k=v`: orice tool din terminal, pentru debug;
- `vedit-eval`: rulează agentul pe cazuri de test (clipuri + cerere + așteptări) și măsoară obiectiv rezultatul;
- Docker + Caddy (HTTPS automat) + systemd pentru VPS (`docs/DEPLOY.md`);
- ghiduri: `docs/TUTORIAL.md`, `docs/TESTARE.md`, `docs/DEPLOY.md`.

---

## Ce NU știe încă

- **Imagine:** nu urmărește obiecte (doar fețe), nu are keyframe-uri libere și nici animații 3D.
- **Dublaj:** nu face lip-sync (buzele nu se potrivesc cu vocea nouă).
- **Neverificat real:**
  - Stripe, Pexels, fal, Replicate și un LLM prin API nu au rulat cu chei adevărate;
  - funcțiile cele mai noi (momente virale, teaser, zoom pe ecran, audiogram, dublaj, cenzură, blur, ritm automat, „ăăă”) sunt testate automat și pe material demo, dar încă nu într-un job complet cu Claude Code.
