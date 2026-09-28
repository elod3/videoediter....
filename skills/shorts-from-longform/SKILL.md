---
name: shorts-from-longform
description: Extrage clipuri scurte virale (TikTok, Reels, YouTube Shorts, 15-60s) dintr-un video lung (podcast, stream, interviu, webinar). Folosește când clientul cere "fă-mi shorts", "clipuri din podcast", "highlights", "cele mai bune momente".
---

# Shorts din long-form

## 1. Găsește candidații (doar din transcript)

Citește transcriptul pe bucăți de 300s. Notează candidați: fragmente de 15-60s care se înțeleg **fără context**.
Punctează fiecare 0-3 pe:

| Criteriu | Ce cauți |
|---|---|
| Hook | primele 3s: afirmație surprinzătoare, întrebare, cifră, conflict, "nimeni nu-ți spune că…" |
| Standalone | nu depinde de "cum ziceam mai devreme", nu are pronume fără referent |
| Payoff | se termină cu o concluzie / punchline / lecție clară |
| Emoție | umor, controversă, poveste personală, bani, greșeli |
| Densitate | fără divagații; cuvinte/secundă mare |

Păstrează top N (implicit 3) cu scor ≥ 10/15. Nu suprapune candidați.

**Podcast / interviu cu 2+ persoane:** rulează `speakers_detect(asset, start, end)` pe zona candidaților.
Îți spune cine vorbește când (`[t0-t1] S0`), deci știi cine spune fraza din transcript. Un short bun are de obicei
un singur vorbitor principal sau un schimb scurt întrebare → răspuns; evită fragmentele cu 4+ schimbări de vorbitor.

## 2. Construiește fiecare short (același proiect, pe rând — transcriptul rămâne în cache)

Setează o singură dată `timeline_format("9:16")`. Apoi pentru fiecare short, pe rând:

1. `keep_words(asset, "wHOOK_a-wHOOK_b,wA-wB")` — **hook-ul poate fi mutat primul** chiar dacă în original vine la final
   (cold open). Apoi restul în ordine cronologică.
2. `cut_silences` NU se aplică după `keep_words` (ar reconstrui timeline-ul). Pentru ritm, folosește `cut_words` pe umpluturi.
3. Skill `vertical-reframe` → `captions_add(style="bold_center")` sau `karaoke`.
4. Titlu scurt (max 6 cuvinte) cu `text_add(0, 2.5, "...", "top")` doar dacă hook-ul vorbit e slab.
   (`keep_words` pornește de la zero: șterge captions și textele short-ului anterior.)
5. Durată țintă: 20-45s. Peste 60s → taie mai mult.
6. `render(preview=false, name="short1")` → `qa_check(path=<cale>)`. Următorul: `short2`, etc.

## 3. Raport

Pentru fiecare short: titlu propus, scor, primul rând (hook), durată, cale fișier.
