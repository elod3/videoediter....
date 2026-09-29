---
name: broll-and-beats
description: B-roll peste vorbire (pista V2), montaj pe beat-ul muzicii și aducerea de footage când clientul nu are (stock Pexels sau generare AI plătită, doar la cerere). Folosește când clientul cere „B-roll”, „pune imagini peste”, „fă-l mai vizual”, „montaj pe muzică / pe beat”, „recap”, „travel / produs / eveniment”, sau când un fișier e marcat [B-ROLL].
---

# B-roll și montaj pe beat

## Decide tipul de montaj

| Material | Montaj |
|---|---|
| cineva vorbește (vlog, UGC, podcast, tutorial) | montajul pe V1 urmează vorbirea (skill-urile de cleanup) + **B-roll pe V2** peste fraze |
| fără vorbire (travel, produs, eveniment, recap) + o piesă | **`beat_montage`**: tăieturile cad pe beat |

## A. B-roll peste vorbire (V2)

Ordinea: tăieturi finale pe V1 → `timeline_view` → abia apoi B-roll (poziția lui e în timp de timeline).

1. Citește transcriptul și marchează frazele care **numesc ceva ce se poate arăta** (un loc, un obiect, o acțiune,
   o cifră). Acolo pui B-roll. Nu pune B-roll pe emoție, pe glume sau pe fraza-hook: acolo contează fața.
2. Reguli de dozaj:
   - primele 2 s (hook) rămân pe vorbitor
   - inserturi de 1.5–3 s; peste 4 s, privitorul pierde firul vocii
   - acoperire totală sub 40% din durată; niciodată două inserturi lipite fără vorbitor între ele
   - dacă există muzică: `snap=true` ca intrarea și ieșirea să cadă pe beat
3. `broll_add(asset, at, duration, src_in)`: alege `src_in` unde se întâmplă ceva în clip
   (`frames_look` pe clipul de B-roll).
4. `mode="pip"` doar când vorbitorul explică ceva de pe ecran (tutorial, reacție); altfel `full`.
5. Verifică: `render(preview=true)` → `frames_look(asset="render:preview")`.

## B. Montaj pe beat

1. `beats_detect(music)`: BPM și beat-uri. Beat-urile sunt precise; downbeat-urile sunt doar estimate.
2. Ritmul după BPM și energie:
   | BPM | beats_per_shot |
   |---|---|
   | < 90 | 2 |
   | 90–130 | 2 (4 pentru un montaj calm) |
   | > 130 | 4 (2 doar pentru ceva foarte alert) |
3. `beat_montage(music, sources, beats_per_shot, max_duration)`. Înlocuiește timeline-ul și pune muzica pe A2.
4. Dacă piesa are o intrare lungă, pornește de la primul beat puternic: `start_beat=N`.
5. Verifică vizual că shot-urile nu se repetă și că primul shot e cel mai puternic (`clip_move`).

## C. Nu există footage de B-roll

Ordinea e obligatorie:
1. **Footage-ul clientului.** Întreabă sau folosește ce e încărcat.
2. **Stock real, gratuit:** `broll_stock(query, count)`. Query în engleză, concret, vizual:
   „barista pouring latte”, nu „cafea bună”. Verifică cu `frames_look` că se potrivește înainte să-l pui.
3. **Generare AI (`broll_generate`), plătită:** DOAR dacă:
   - utilizatorul a cerut explicit generare („generează”, „fă cu AI”), SAU
   - nu există footage, stock-ul nu are nimic potrivit ȘI utilizatorul a acceptat generarea.

   Prompt bun: subiect + acțiune + cadru + lumină + stil de cameră, în engleză, fără text, logo-uri sau
   persoane reale: „slow dolly shot of steam rising from a coffee cup on a wooden table, morning window
   light, shallow depth of field, 35mm”. Un clip generat = 4-6 s; generează doar cât pui efectiv.

În raportul final spune de unde vine fiecare B-roll (client / Pexels + autor / generat AI + provider).

## Tranziții și zoom animat (finisaj)

- **Vorbire (vlog, UGC, tutorial):** tăieturile rămân DURE. Tranziții doar la schimbarea de idee sau de secțiune:
  `transition_set(clip, "fadeblack"|"dissolve", 0.3-0.5)`. Pe jump-cut-uri, tranzițiile arată amatoricesc.
- **Montaj pe beat:** cel mult o tranziție la 4-8 shot-uri, pe downbeat. `fadewhite` (flash) 0.15-0.25 s pe drop,
  `hblur` (whip) 0.2-0.3 s între locuri, `zoomin` 0.3 s pe intrarea în refren.
- **Zoom animat:** `zoom_animate(clip, 1.12)` pe clipurile lungi (> 4 s) fără tăieturi, ca imaginea să nu stea;
  pe B-roll static (produs, peisaj) Ken Burns 1.0 → 1.15. Nu pune zoom animat pe clipurile care au deja punch-in.
- Tranzițiile scurtează montajul (clipurile se suprapun): verifică durata cu `timeline_view` după.

## Nu face

- Nu pune B-roll generat unde clientul are footage real.
- Nu genera oameni care vorbesc sau produse ale clientului: AI-ul inventează detalii greșite.
- Nu lăsa B-roll-ul peste subtitrările cheie fără să verifici că se citesc (subtitrările stau deasupra V2).
