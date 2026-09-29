---
name: edit-brief
description: Transformă cererea vagă a unui client ("fă-l viral", "ceva pentru Instagram", "curăță-l") într-o specificație de editare precisă, înainte de a edita. Folosește la începutul fiecărui job din SaaS.
---

# Edit brief → spec

Clientul scrie vag. Tu produci un spec JSON explicit și îl urmezi. Nu pune întrebări dacă poți deduce;
alege valorile implicite de mai jos și menționează-le în raport.

## Deducții implicite

| Clientul spune | platform | format | durată | ritm | captions |
|---|---|---|---|---|---|
| tiktok / reels / shorts / viral | tiktok | 9:16 | 20-45s | agresiv | bold_center |
| youtube (fără "shorts") | youtube | 16:9 | păstrează | normal | classic_bottom |
| instagram feed / post | instagram | 4:5 | ≤60s | normal | bold_center |
| podcast / interviu | youtube | 16:9 | păstrează | lent | classic_bottom |
| reclamă / ad / UGC | tiktok | 9:16 | 15-30s | agresiv | karaoke |

Dacă există un clip `[REFERINȚĂ]`, tabelul de mai sus nu mai decide: formatul, ritmul și culoarea vin din
`reference_analyze` (skill `reference-style`).

## Spec (scrie-l în răspuns înainte de editare)

```json
{
  "platform": "tiktok",
  "format": "9:16",
  "target_duration_s": [20, 45],
  "pace": "aggressive|normal|slow",
  "tasks": ["cleanup", "shorts", "reframe", "captions", "music", "graphics", "sfx", "multicam"],
  "caption_style": "bold_center",
  "hook": "descrie hook-ul ales sau 'din transcript'",
  "music": "a1 | none",
  "n_outputs": 1
}
```

Apoi mapează `tasks` la skill-uri: cleanup → `talking-head-cleanup`, shorts → `shorts-from-longform`,
reframe → `vertical-reframe`, captions → `captions-and-text`, music → `audio-mix`, referință / culoare → `reference-style`, B-roll / montaj pe muzică / footage lipsă → `broll-and-beats`,
graphics / sfx / viteză / efecte → `motion-graphics`, mai multe camere ale aceluiași moment → `multicam`,
mereu la final → `qa-and-delivery`.

Cereri de stil fără detalii:
- „mai dinamic / mai profesional / să arate scump” → `graphics` + `sfx` (câteva, cu motiv) pe lângă tăieturi.
- „ca MrBeast / Hormozi” → ritm agresiv, subtitrări mari, `title_card` + `counter` pe cifre, `sfx_auto`.
- 2+ clipuri video ale aceluiași moment (aceleași persoane, durate apropiate) → `multicam`, chiar dacă clientul
  nu folosește cuvântul.
