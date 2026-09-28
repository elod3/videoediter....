---
name: vertical-reframe
description: Reîncadrează un video orizontal (16:9) pentru vertical (9:16) sau pătrat, ținând subiectul în cadru, cu punch-in-uri pentru dinamism. Folosește după ce tăieturile sunt făcute și formatul e setat pe 9:16, 1:1 sau 4:5.
---

# Vertical reframe

Crop-ul 9:16 dintr-un 16:9 păstrează doar ~32% din lățime. Dacă subiectul nu e pe centru, îl pierzi.

## Pași

1. `frames_look(asset, cols=4, rows=3)` pe tot asset-ul (sau pe intervalul folosit).
2. Pentru fiecare celulă estimează **centrul orizontal al feței/subiectului** ca fracție 0..1 din lățime
   (0 = marginea stângă, 0.5 = centru). Celulele au timestamp → mapează-le pe clipuri (`timeline_view` arată src_in/src_out).
3. Grupează clipurile cu subiectul în aceeași poziție și aplică `reframe(clip_ids="c0,c1,c2", cx=0.38)`.
   Toate la fel → `reframe("all", cx=...)`.
4. **Două persoane** (podcast): pentru fiecare clip, încadrează pe cine vorbește. Dacă nu poți ști din imagine,
   folosește `fill="pad"` (`timeline_format("9:16", fill="pad")`) în loc să ghicești.
5. **Punch-in** pentru ritm: alternează `zoom=1.0` și `zoom=1.15-1.25` pe clipuri consecutive (la fiecare tăietură),
   mai ales în talking-head. Nu depăși 1.35 (pixelare pe surse 1080p).
6. `cy`: lasă 0.5; pune 0.4 dacă fața e sus în cadru și captions vin la mijloc.

## Verificare

`render(preview=true)` → `frames_look(asset="render:preview")` → verifică în fiecare celulă că fața e în cadru
și nu e acoperită de captions. Dacă nu, ajustează `cx`/`cy` pe clipurile respective și re-randează preview.
