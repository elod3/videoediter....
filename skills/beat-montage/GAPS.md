# GAPS: ce nu se poate face încă cu tool-urile vedit (ordonat după impact)

**Stare (18 oct 2026):** implementate în motor: 1.1 parțial (`beat_montage(pattern, lead)`; fără `pickup`, `motion`,
`pick`, `kicks`), 1.2 și 1.5 ca `beat_fx(kind="rgb"|"punch"|"flash")` (rgb pe ferestre de 3 cadre, punch prin
`perspective` cu cadru de mărime fixă). Restul de mai jos e încă deschis.

Toate filtrele marcate „testat” au rulat pe clipul de referință cu ffmpeg-ul din `.tools` (libx264, 60 fps, 540x960) și au dat
imaginea așteptată. Nu sunt integrate în `render.py`. Contextul din `render.py` (verificat): efectele per clip sunt în `_fx` și
în `nodes.compile_graph`; tranzițiile în `_join` / `PRO_TRANSITIONS`; `t` din expresiile unui clip e timpul DIN CLIP (se
resetează la fiecare clip), iar `t` după `_join` e timpul de montaj. Efectele pe beat trebuie puse DUPĂ `_join` ca să
folosească timpul de montaj (altfel nu cad pe beat).

Notație: `P` = perioada beat-ului în secunde (60/BPM, ex. 0.5217), `OFF` = momentul primului beat pe montaj (`beats[i] - music.src_in`).

---

## 1.1 Lungimi variabile pe grila de beat + offset de tăiere (impact: foarte mare)
**Problema:** `beat_montage` taie în felii egale (`beats_per_shot` fix) exact pe beat. Referința are 1/2/4 beat-uri amestecate și
tăieturi la beat - 0.03 s. Acum agentul trebuie să facă 15-30 de `clip_add` manual, cu aritmetică pe beat-uri.
**Implementare (Python, `Project.beat_montage` în `vedit/project.py`):**
- parametri noi: `pattern: str = ""` (ex. `"1,1,2,4,4,2,1,1,1,1,1,1,2,1,1,4,3,2"`, ciclic dacă e mai scurt decât piesa),
  `lead: float = 0.03`, `pickup: float = 0.0`.
- `slots`: construiește cu `idx` cumulat: `a = beats[idx]`, `b = beats[idx + n]`, apoi `idx += n`. Capetele: `a - lead`, `b - lead`
  (prima felie pornește la `a - lead - pickup`). Durata = `b - a`, deci nu se acumulează drift.
- `Music.src_in = round(beats[start_beat] - lead - pickup, 3)`.
- opțional `motion: bool = True`: pe fiecare clip pune `keys=[{"t":0,"zoom":1.28,"cx":0.45|0.55,"cy":0.42,"ease":"expo"},{"t":dur,"zoom":1.0}]`
  + `motion_blur=True` (aceeași structură ca `clip_keyframes`), alternând `cx`.
- opțional `pick="alternate"`: alege shot-ul următor cu luminanță medie diferită de cel precedent (cache `_cache(s, "luma", ...)` din `analyze.py`).
- expune și onset-urile joase: `beats.py` are `onset_envelope` și `LOW_BANDS`; adaugă în `Beats` câmpul `kicks: list[float]` (vârfuri pe banda joasă,
  prag 0.35, separare 0.15 s; testat pe referință: 0.26, 3.9, 5.99, 7.04, 9.13, 9.65). `beat_montage(snap_to_kicks=True)` mută granițele
  lungi (>= 2 beat-uri) pe kick-ul cel mai apropiat (< 0.06 s).
- test: `tests/test_beats_broll.py` + `drums.py`: tăieturile cad la `beat - 0.03 +- 0.01`.

## 1.2 RGB split pulsat pe beat (impact: mare; „look-ul” unui car/product edit)
Există `clip_fx glitch` (rgbashift în rafale la `mod(t,0.6)`, nu pe beat, per clip) și nodul `chromatic` (constant). Lipsește pulsul pe beat.
`rgbashift` nu acceptă expresii pe cadru, deci se separă canalele și se decalează cu `crop` (expresii pe `t`).
**Filtru (testat, 540 wide, A=16 px):**
```
[v]format=gbrp,split=3[a][b][c];
[a]lutrgb=g=0:b=0,pad=iw+2*A:ih:A:0:black[r0];
[b]lutrgb=r=0:b=0,pad=iw+2*A:ih:A:0:black[g0];
[c]lutrgb=r=0:g=0,pad=iw+2*A:ih:A:0:black[b0];
[r0]crop=W:ih:x='A-A*PU':y=0[r];
[g0]crop=W:ih:x=A:y=0[g];
[b0]crop=W:ih:x='A+A*PU':y=0[b];
[r][g]blend=all_mode=lighten[rg];[rg][b]blend=all_mode=lighten,crop=W-2*A:ih:A:0,scale=W:H,format=yuv420p[out]
```
cu `PU = max(0,1-mod(t+OFF',P)/0.14)` (puls care scade în 0.14 s după fiecare beat; `OFF' = P - OFF mod P` ca să pornească pe beat).
`A` ~ `short*0.015` (la 1080: 16 px). Pentru „doar pe tranziții” folosește `between(t,a,b)` în loc de `mod`.
**Unde:** nod nou `rgbpulse` în `vedit/nodes.py` (params: `amount` % din cadru, `decay` s, `every` beat-uri = 1/2/4), compilat ca `glow` (mai multe lanțuri
în `cx.chains`), dar cu `t` de montaj: mai simplu ca strat global `Timeline.beat_fx = [{"kind":"rgbpulse","bpm":..,"offset":..,"every":2,"from":..,"to":..}]`
aplicat în `build_command` după `_join`. Tool: `beat_fx_add(kind, every, start, end)`.
Notă: în testul rulat am lăsat benzile de margine (un singur canal) vizibile; `crop=W-2*A:ih:A:0,scale=W:H` de la final le taie (netestat separat, dar e un crop + scale standard), deci zoom ~3%.

## 1.3 Speed ramp neted, nu în trepte (impact: mare)
`speed_ramp` împarte clipul în `steps` segmente cu viteze constante (vizibil la < 6 trepte; fiecare segment poate primi tranziție).
Referințele de car edit folosesc rampe continue.
**Filtru (testat: 1x -> 3x pe 2 s sursă = 1.13 s montaj, matematic ln(3)=1.0986 s):** viteza crește liniar cu timpul-sursă:
```
setpts='(D/(S1-S0))*log((S0+(S1-S0)*(PTS-STARTPTS)*TB/D)/S0)/TB'
```
`D` = durata sursă a clipului (s), `S0` / `S1` = viteza la început / sfârșit. Durata pe montaj = `D/(S1-S0)*ln(S1/S0)` (dacă `S0==S1`: `D/S0`).
Funcționează și la încetinire (`S1<S0`). Pentru calitate la accelerare: `...,tmix=frames=2:weights='1 1'` (amestec de cadre, motion blur fals) sau
`minterpolate=mi_mode=blend`; la încetinire din 25-30 fps: `minterpolate=fps=60:mi_mode=mci` (lent, doar clipuri scurte). Audio: tăiat (`volume_db=-99` e deja regula pe montaj), nu `atempo`.
**Implementare:** `Clip.ramp: tuple[float,float] | None`; în ramura de viteză din `render.py` (unde se pune `setpts=PTS/speed` + `_atempo`) înlocuiești cu formula; `Clip.duration` =
durata de mai sus (deja centralizată în `Clip.duration` / `src_at` / `tl_at`; actualizează-le: `tl_at(s) = D/(S1-S0)*ln((S0+(S1-S0)*s/D)/S0)`).
`speed_ramp` primește `smooth: bool = True`.

## 1.4 Halation roșu + bloom fizic (impact: mediu-mare, doar pentru look „film”)
Nodul `glow` e doar alb (`blend screen` pe praguri). Halation real = lumină roșie-portocalie în jurul surselor de lumină.
**Filtru (testat; arată un halo cald discret pe fantele și lumini):**
```
[v]format=gbrp,split[a][b];
[b]lutrgb=r='if(gt(val,T*maxval),val,0)':g='if(gt(val,T*maxval),val,0)':b='if(gt(val,T*maxval),val,0)',
   colorchannelmixer=rr=1:gg=0.28:bb=0.05,gblur=sigma=SIG[h];
[a][h]blend=all_mode=screen:all_opacity=0.7
```
`T`=0.8 (prag), `SIG` ~ `short*0.02` (la 1080: 21; la 540: 14). Mai mult roșu: `gg=0.15`; mai portocaliu: `gg=0.4`. O sursă clipată (alb 255) dă halo doar dacă
pragul e sub ea: păstrează T <= 0.85. Doar roșul pentru film cu emulsie: `colorchannelmixer=rr=1:gg=0:bb=0`.
**Implementare:** parametri `tint` (`white|warm|red`) și `mode` în nodul `glow` din `nodes.py` (linia cu `lutrgb`), sau nod `halation`. Preset „film” în `color_grade`: halation 0.5 + `grain` 6 + `vignette`.
Notă: referința GT3 nu are halation; nu-l promite ca „look de referință”, ci ca opțiune.

## 1.5 Pulsuri pe beat: flash de expunere, zoom, shake (impact: mare, ieftin)
Acum: `clip_fx flash` (doar la intrarea în clip), `shake` continuu (`sin(t*23)`, nu pe beat). Lipsește pulsul sincron cu muzica.
**Filtre (după `_join`, `t` = timp de montaj; `eq` testat):**
- flash de expunere pe fiecare beat: `eq=brightness='0.22*max(0,1-mod(t+OFF',P)/0.09)':eval=frame`
- zoom puls (punch pe beat): `scale=w='W*(1+0.05*PU)':h='H*(1+0.05*PU)':eval=frame,crop=W:H` cu `PU=max(0,1-mod(t+OFF',P)/0.15)`
- shake pe beat: `crop=W-2*A:H-2*A:x='A+A*sin(t*60)*PU':y='A+A*cos(t*47)*PU',scale=W:H`
Se declară ca `Timeline.beat_fx` (vezi 1.2): `kind` flash|zoom|shake|rgbpulse, `every`, `from`/`to` (secunde de montaj), `amount`. Tool: `beat_fx_add`, `beat_fx_clear`.
Sunt cele mai ieftine efecte de „energie” pe rafala de shot-uri de 1 beat.

## 1.6 Insert circular cu fisheye, pe fundal negru (impact: mediu; documentar / vlog)
`broll_add(frame=...)` are `rounded`, `phone`, `laptop`; nu cerc / fisheye (inserturile rotunde din vlogul de referință).
**Filtre (testat, 2 s în 0.85 s CPU; `geq` DOAR pe masca gray, niciodată pe RGBA: `geq` pe 3 canale nu s-a terminat în 2 min, abandonat):**
```
[0:v]crop=ih*0.56:ih*0.56,scale=S:S,lenscorrection=k1=-0.4:k2=0,format=yuva420p[v];
color=c=white:s=SxS:r=FPS:d=DUR,format=gray,geq=lum='if(lt(hypot(X-W/2,Y-H/2),W*0.47),255,0)'[m];
[v][m]alphamerge[c];
color=0x0a0a0a:s=WxH:r=FPS:d=DUR[bg];
[bg][c]overlay=0:(H-h)/2,format=yuv420p
```
Alb-negru (look din referință): `hue=s=0,eq=contrast=1.15` înainte de `alphamerge`. Subtitrare roșie sub cerc: există deja `captions_look` + `motion_style`.
**Implementare:** `frame="circle"` în `broll_add` (cu `pip_pos=center`) + parametru `bg="#0a0a0a"` care pune fundal plin dedesubt pe durata inserției.

## 1.7 Split edits reale (J-cut / L-cut pe V1) (impact: mediu; documentar)
Clipul are audio legat de imagine. Acum J/L se imită cu `broll_add` (imaginea de pe V2 acoperă vocea de pe V1), ceea ce merge pentru B-roll, dar nu
pentru „vocea din scena următoare începe cu 0.5 s înainte de imagine” între două clipuri cu vorbitor.
**Implementare:** `Clip.a_lead: float = 0` (secunde de audio al clipului care intră înainte de imagine) și `a_tail: float = 0` (audio al clipului care continuă peste
clipul următor). În `render.py`: audio-ul clipului k folosește `atrim=start={src_in - a_lead}:end={src_out + a_tail}`, `asetpts=PTS-STARTPTS`,
`adelay` = `-a_lead` față de imagine; în `_join` înlocuiești `concat` cu `acrossfade=d=a_lead` între audio. `Timeline.starts()` rămâne pentru imagine.
Tool: `split_edit(clip_id, lead=0.5, tail=0)`.

## 1.8 Etichete HUD urmărite (verde neon, contur de cutie) (impact: mediu; vlog)
`motion_add("pin", ..., track=...)` urmărește un punct, dar nu desenează „etichete de preț / cutii de detecție” (referința Schafer: etichete verzi `$13.49` pe jucării,
contururi roșu/verde pe rafturi cu text mic monospațiat). **Implementare:** bloc nou `vedit/motion/blocks/hud_tag.html`: dreptunghi cu contur 2 px în accent
(`#39FF14` implicit), colțuri „reticule”, text mono 14-18 px (în stil `reel`), intrare cu scan/blink 0.15 s; params `text`, `x`, `y`, `w`, `h`, `color`, `kind`
(`price`|`box`|`label`); lucrează cu `track_point` (ca `pin`). Până atunci: `motion_add("pin")` cu `motion_style(palette="#39FF14")` și `graphic_add("callout")`.

## 1.9 Textură „film” coerentă (grain organic, gate weave, expunere flicker) (impact: mic)
Acum: `grain` = `noise=alls=N:allf=t` (zgomot alb, uniform, același pe luminanță și crominanță). Mai fidel:
`noise=c0s=6:c0f=t+u:c1s=3:c1f=t+u:c2s=3:c2f=t+u` (crominanță mai slabă, aer filmic), gate weave: `crop=W-6:H-6:x='3+2*sin(t*5.1)':y='3+1.5*sin(t*3.7)',scale=W:H`,
flicker: `eq=brightness='0.012*sin(t*37)':eval=frame`. Un preset `film` în `color_grade` care le combină cu 1.4.

## 1.10 Analiza shot-urilor pentru alegere automată (impact: mediu)
Un `shots_rank(asset)` care întoarce pentru fiecare scenă: luminanță medie, energie de mișcare (diferență medie între cadre, ca în breakdown), claritate
(Laplacian), prezența feței. Agentul alege shot-urile cu mișcare pe început de beat și evită cadrele neclare. Se face din `analyze.py` (ffmpeg `signalstats` + `scale=108:192` + numpy).

## Nu e gap, dar e limită de știut
- `speed_ramp` + `transition_set` pe același clip: prima bucată păstrează tranziția, restul nu (corect).
- `transition_set` pe clipuri < 0.16 s e ignorat (verificat: un clip de 0.1 s nu primește tranziție).
- Tranziția scurtează montajul cu `duration`: `clip_trim(src_out + d)` pe clipul precedent compensează (verificat pe un timeline de test).
- `fx glitch` randează rafale la `mod(t, 0.6)`, nu pe tăietură; pentru tăietură folosește `transition_set(type="glitch")`.
