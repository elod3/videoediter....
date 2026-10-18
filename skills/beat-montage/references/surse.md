# Surse (căutare web, octombrie 2026) și cât de mult se bazează skill-ul pe ele

Concluziile de ritm, grade și tranziții din SKILL.md vin din **măsurarea referinței** (`breakdown-Dd6peYGIFjr.md`), nu din
tutoriale. Tutorialele de „car edit” și „speed ramp” de pe web sunt în mare parte pagini de marketing (șabloane
CapCut, gig-uri); le-am folosit doar pentru terminologie. Ce e verificat vs. neverificat e marcat.

## RGB split / aberație cromatică
- Motion Array, „Create an RGB Split Effect in Premiere Pro CC” - metoda de bază: 3 copii, fiecare un canal (R/G/B),
  decalate pe poziție, keyframe-uri care se întorc la 0 la final.
  https://blog.motionarray.com/learn/premiere-pro/rgb-split-effect-premiere-pro/
- Filmbro, „RGB Split & Ripple Transitions like YouTube Rewind” - strat de ajustare de ~10 cadre (5 + 5 în jurul tăieturii),
  tăiere pe vârfurile din waveform. https://filmbro.com/blogs/tutorials/how-to-create-rgb-split-ripple-transitions-like-in-youtube-rewind
- Filmbro, „RGB Glitch Transition” (Channel Mixer + Transform). https://filmbro.com/blogs/tutorials/how-to-create-a-rgb-glitch-transition-in-premiere-pro
- Verificat în vedit: filtrul propus în GAPS 1.2 (3 canale separate, crop animat pe `mod(t, perioada)`) produce franjuri R/B pulsate (testat pe clipul de referință).

## Halation / film emulation
- Dehancer, „Halation” - lanț fizic: sursa strălucitoare trece prin emulsie, se reflectă în baza peliculei și re-expune
  stratul roșu. Parametri: prag pe sursă, difuzie locală, nuanță (roșu -> portocaliu), „Amplify”. Avertisment: halo mic,
  nu bloom uriaș; sursa să nu fie clipată; nu confunda cu bloom.
  https://blog.dehancer.com/halation/
- Mixing Light, „Emulating Film Halation in DaVinci Resolve” (prag + blur + tentă caldă + screen).
  https://mixinglight.com/color-tutorial/emulating-film-halation-in-davinci-resolve
- Digital Production, „Halation and diffusion - On the hunt for the ultimate film look”.
  https://digitalproduction.com/2024/01/30/halation-and-diffusion-on-the-hunt-for-the-ultimate-film-look/
- Nicio sursă găsită pentru FFmpeg; lanțul din GAPS 1.4 (prag `lutrgb` + `colorchannelmixer` roșu + `gblur` + `blend=screen`) e al nostru, testat.
- Notă: referința GT3 NU are halation vizibil (grade curat, rece). Halation = opțiune de look, nu cerință.

## Beat sync / speed ramp
- CapCut, „Beat Detection Workflow” (marcare beat-uri, tăiere, viteză pe segmente) - slab, pagină de produs:
  https://www.capcut.com/create/beat-detection-workflow-goal-compilation-edits
- Sfat repetat în sursele de speed ramp: puține rampe (2-3 într-un clip), accelerezi înainte de beat și încetinești pe el;
  rampa trebuie verificată pe muzică. Surse de calitate scăzută (șabloane, gig-uri): freevisuals.net, capcut.com/explore/speed-ramp-car-edit.
- Neverificat pe web: „tăierea cu 1-2 cadre înainte de beat”. E **măsurat** pe referință: 17 tăieturi, toate la 0.02-0.05 s
  înaintea beat-ului detectat de `vedit.beats` (114.9 BPM).

## Split edits (J-cut / L-cut) și sunet
- Epidemic Sound, „What are J-cuts and L-cuts” - definiții, când se folosesc (J: forță înainte / hook; L: explicație peste
  B-roll), netezirea cu crossfade; nu dă număr de cadre, „trial and error”. https://www.epidemicsound.com/blog/j-cuts-and-l-cuts/
- Krotos, „4 Whoosh Sound Effects Tips” (whoosh stratificat și sincronizat cu mișcarea). https://krotos.studio/guide/4-whoosh-sound-effects-tips
