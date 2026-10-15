---
name: thumbnail
description: Thumbnailuri și coperte care se văd în feed - alegerea cadrului, textul, stilul (cadru sau persoană decupată), formatele YouTube / copertă verticală / feed și verificarea la mărimea de telefon. Folosește la „fă un thumbnail”, „copertă”, „cover”, „poza de la video”, „să atragă click”, sau înainte de orice postare pe YouTube.
---

# Thumbnail

Un thumbnail se judecă la mărimea la care îl vede omul: ~360 px lățime pe YouTube (telefon), ~200 px o
copertă în grila de profil. La mărimea asta trebuie să se vadă trei lucruri: o față (sau produsul), o emoție
sau o stare, maxim 4 cuvinte.

## Pașii

1. `thumbnail_variants(title="...", count=4, formats="youtube" | "cover" | "feed", styles="frame,sticker")`
   - `formats` gol = după formatul proiectului; pentru YouTube cere explicit `youtube`, chiar dacă clipul e vertical.
   - `times="3.2,14.8"` dacă știi momentele bune (reacția, rezultatul, produsul în mână).
2. Uită-te la `renders/thumbs/sheet.png` (`frames_look` sau vision). Pentru fiecare variantă:
   - fața e mare, clară, cu ochii deschiși și o expresie care se potrivește cu titlul?
   - titlul se citește la mărimea din planșă? nu stă peste față? nu e tăiat?
   - e diferită de restul feed-ului clientului (alt cadru, altă culoare dominantă)?
3. Alege 1-2 și spune de ce, în două propoziții. Dacă niciuna nu trece, refă cu alte `times` sau alt titlu.
4. Fișierul ales merge în `post_prepare(cover=...)` (YouTube) sau dă `cover_at` cu secunda lui (Reels/TikTok).

## Textul de pe thumbnail

- 2-4 cuvinte, care COMPLETEAZĂ titlul video-ului, nu-l repetă. Titlu: „Plăcuțe de frână: când le schimbi”;
  thumbnail: „PREA TÂRZIU?” sau „3 SEMNE”.
- O cifră concretă bate un adjectiv („-40% consum”, nu „ECONOMIE URIAȘĂ”).
- Fără clickbait pe care clipul nu-l livrează: dacă thumbnailul promite, clipul arată în primele 10 secunde.
- Fără săgeți roșii, cercuri și fețe „șocate” trase cu forța: sunt semnul thumbnailurilor ieftine. Folosește
  o expresie reală din clip.

## Stiluri

- `frame`: cadrul real + titlul în zona liberă (departe de față). Bun când fundalul spune ceva
  (atelierul, șantierul, terenul).
- `sticker`: persoana decupată, cu contur alb, peste fundalul încețoșat; titlul trece prin spatele ei
  sau vine în față când persoana umple cadrul. Bun pentru o față expresivă, la bust.

## Formate

| format | mărime | unde | zona sigură pentru text |
|---|---|---|---|
| `youtube` | 1280×720 | thumbnail YouTube (urcat cu `cover=`) | evită colțul dreapta-jos (durata) |
| `cover` | 1080×1920 | coperta Reels / TikTok / Shorts | 20%-64% din înălțime (butoanele aplicației + grila 3:4) |
| `feed` | 1080×1350 | postare 4:5 în feed-ul Instagram | 15%-82% |
