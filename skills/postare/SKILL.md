---
name: postare
description: Pregătirea și publicarea unui clip pe conturile clientului (YouTube, Instagram, Facebook, TikTok) - titlu, descriere, hashtaguri, copertă, ora, vizibilitate, CTA-uri și dezvăluiri, pe regulile fiecărei platforme. Folosește când omul zice „postează”, „urcă pe YouTube/Insta/TikTok”, „pregătește postarea”, „ce descriere punem”, „programează-l”, sau după ce un clip e gata și urmează livrarea.
---

# Postare

Tu pregătești; omul publică. Nimic nu pleacă pe contul unui client fără ca omul să fi văzut previzualizarea
și să fi spus clar „publică” pentru ACEL pachet.

## 1. Înainte să scrii ceva

1. `post_accounts(project)`: pe ce conturi se poate posta (doar ale clientului legat de proiect).
   Dacă proiectul nu e legat sau lipsește un cont, spune-i omului comanda exactă și oprește-te.
   Nu încerca niciodată alt cont decât cele listate.
2. Clipul e randat pentru platformă: `export_preset(platform)` (reels / tiktok / shorts / youtube).
   Un singur fișier pe platformă; nu urca același mp4 de 16:9 pe Reels.
3. Află de la om (sau din brief), dacă nu știi deja: ce vrea clientul să facă omul care vede
   (sună, vine, comandă, se abonează, scrie în DM), ce cuvânt cheie caută clienții lui, dacă e
   parteneriat plătit, dacă e făcut pentru copii, dacă are părți generate cu AI.

## 2. Coperta

- YouTube: `thumbnail_variants(title="2-4 cuvinte", formats="youtube")`, apoi te uiți la `sheet.png`
  (e la mărimea din feed-ul de telefon). Alege 1-2 și spune de ce. Reguli: o față mare și clară,
  titlul se citește la 360 px lățime, maxim 4 cuvinte, nu repeta titlul video-ului cuvânt cu cuvânt.
- Reels / TikTok / Shorts: coperta e un cadru (`cover_at` în secunde). Alege cadrul din planșa
  `thumbnail_variants(formats="cover")`; textul de pe copertă stă între 20% și 64% din înălțime
  (jos și în dreapta sunt butoanele aplicației, iar grila profilului taie coperta la 3:4).

## 3. Textele, pe platformă

| | YouTube | Instagram (Reels) | Facebook (Reels) | TikTok |
|---|---|---|---|---|
| unde | `title` + `caption` (descriere) | `caption` | `caption` | `title` (e textul postării) |
| limită | titlu 100, descriere 5000 octeți, fără `<` `>` | 2200 caractere, **max 5 hashtaguri** | lung, dar se taie după ~2 rânduri | 2200 |
| primul rând | titlul: cuvântul căutat în primele 40 de caractere | singurul văzut înainte de „mai mult”: cârligul sau promisiunea | la fel ca Instagram | primele ~70 de caractere |
| programare | da (`schedule_at`) | nu: publică la ora aleasă | da, max 75 de zile | nu |
| vizibilitate | public / unlisted / private | public | public | public / friends / followers / private* |

\* Cât timp aplicația TikTok n-a trecut de audit, se poate posta doar `private`; dacă omul vrea public,
spune-i asta, nu încerca.

**YouTube** (și Shorts):
- titlul spune ce primește omul, cu cuvântul pe care îl caută („Plăcuțe de frână: când le schimbi”), nu
  „Video nou!!!”;
- descrierea: rândul 1-2 rezumă clipul cu cuvântul căutat; apoi ce află omul (2-4 rânduri scurte);
  apoi acțiunea: telefon, adresă, link de programare; apoi „Abonează-te dacă…” cu un motiv concret
  („…dacă vrei câte un sfat de service în fiecare marți”), nu „Like & subscribe”;
- capitole (`chapters_set`) doar la clipuri peste 2 minute;
- `options`: `{"made_for_kids": false}` e OBLIGATORIU (spune adevărul; true doar dacă publicul țintă sunt
  copiii), `tags` câteva cuvinte căutate, `contains_synthetic_media: true` dacă oamenii/locurile reale
  sunt generate sau modificate cu AI.

**Instagram / Facebook**:
- primul rând = cârlig sau promisiune, în cuvintele clientului;
- 2-4 rânduri scurte, apoi acțiunea („Programări: 0740 … sau link în bio”);
- 3-5 hashtaguri precise (oraș + serviciu + nișă: `#targumures #servicemures #frane`), puse la final;
  Instagram refuză peste 5, iar hashtagurile generice (`#love #instagood`) nu aduc nimic;
- `cover_at` = cadrul cel mai clar cu fața sau produsul; `options`: `share_to_feed` (implicit true),
  `trial: true` pentru un Trial Reel (îl vede întâi doar cine nu urmărește contul).

**TikTok**:
- textul scurt, vorbit, cu 2-4 hashtaguri de nișă; cuvântul căutat în text, pentru căutarea din TikTok;
- `options`: `is_aigc: true` dacă are conținut generat cu AI; `brand_content: true` dacă e parteneriat plătit
  cu altă firmă (nu poate fi privat); `brand_organic: true` dacă clientul își promovează propria afacere.

**Pentru toate**: textul trece regula anti-slop (fără „Descoperă…”, „În lumea de azi”, „la următorul nivel”,
emoji pe fiecare rând, triade de adjective). Dacă ai skill-ul `scenarist-social`, folosește-i catalogul
de clișee. Cifrele și promisiunile vin de la client; nu inventa prețuri, rezultate sau recenzii.

## 4. Pregătirea pachetului

`post_prepare(project, platform, video="renders/<platform>.mp4", caption=..., title=..., hashtags="#a #b",
privacy=..., schedule_at="2026-10-20T18:30:00+03:00", cover="renders/thumbs/2_youtube_sticker.png",
cover_at=3.2, options='{"made_for_kids": false}')`

- Câte un pachet pe platformă. Citește erorile și avertismentele și repară-le.
- Arată-i omului previzualizarea întreagă (contul, textul exact, coperta, ora). Întreabă-l dacă publică.

## 5. Publicarea

- `post_publish(project, package)` doar după ce omul a zis „publică” pentru pachetul ăla. „Arată bine” nu
  e acord de publicare.
- Dacă tool-ul răspunde `REFUZAT`, nu încerca altă cale: spune-i omului comanda
  `vedit-accounts publish <proiect> <pachet>` și oprește-te.
- După publicare: dă linkul și avertismentele (YouTube privat până la audit, thumbnail nepus etc.).
- Un pachet publicat nu se republică. Pentru o variantă nouă, pregătește alt pachet.
