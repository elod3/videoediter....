# Decizia estetică (după standardul fara-ai-slop)

**Public:** creatori și agenții mici care editează 5-50 clipuri pe săptămână. Știu ce e un timeline,
nu vor să învețe Premiere. Au încredere în agent doar dacă văd exact ce a tăiat.

**Ton:** unealtă de montaj, nu landing de SaaS. Limbajul vine din post-producție: timecode
(`00:00:03:12`), piste `V1 / SUB / TXT / A1`, jurnalul de montaj numerotat ca un EDL.

**Elementul memorabil:** jurnalul agentului. Fiecare tăietură apare ca rând de EDL
(`003  auto_reframe  cx 0.19 → 0.80 la 00:00:03:00`), iar în timeline clipurile se mută
vizibil când agentul taie. Transparența asta e argumentul produsului, așa că e și singura mișcare.

**Alegeri conștiente:**
- **Temă întunecată:** justificată de domeniu. Editoarele video (Resolve, Premiere, CapCut) sunt
  întunecate ca să nu influențeze percepția culorii în imagine. Nu e aleasă ca să pară „tech”.
- **Tipografie:** Archivo (lățime variabilă: expanded pentru titluri, normal pentru text) +
  JetBrains Mono doar pentru date: timecode, nume de tool-uri, cifre. Fonturile sunt găzduite local.
- **Culoare:** gri neutru (fără nuanță albastră) + un singur accent lime, cerut prin referința
  Higgsfield. Apare doar pe acțiunea principală, pe playhead și pe selecție. Clipurile din timeline
  au tonuri stinse, câte unul per sursă, ca în editoarele reale.
- **Colțuri:** 4 px la controale, 8 px la panouri. Fără pastile, fără glow, fără blur.
- **Mișcare:** doar clipurile din timeline (poziție și lățime, 260 ms) și rândurile noi din
  jurnal. Ambele arată o schimbare făcută de agent. Se respectă `prefers-reduced-motion`.

## Editorul ca NLE (octombrie 2026)

**De ce s-a schimbat:** pentru o tăietură mică nu are sens să aștepți agentul. Editorul arată acum ca
unealta pe care publicul o știe deja: CapCut pentru aranjament, Resolve pentru limbaj.

- **Aranjament CapCut:** bara de unelte verticală la stânga (icon + etichetă), sertarul ei, monitorul în centru,
  proprietățile selecției în dreapta, timeline-ul pe toată lățimea jos, cu bara de unelte deasupra
  (Taie / Scurtează / Dublează / Șterge, cu tasta afișată lângă fiecare).
- **Din Higgsfield:** agentul e o căsuță mare, cu sugestii scurte deasupra, iar accentul lime rămâne doar pe
  acțiunea principală (Export final), pe playhead și pe selecție (inclusiv mânerele de trim ale clipului selectat).
- **Monitor live:** redă din surse, fără randare. Randarea rămâne pentru rezultatul exact.
- **Mișcare:** clipurile își animă poziția doar când le mută altcineva (agentul, un undo, un import din Resolve).
  Când tragi tu, animația se oprește, ca mouse-ul să nu „alunece”.

## Modul de editare (octombrie 2026)

**De ce:** agentul are un editor întreg; omul trebuie să aibă și el unul. Modul de editare scoate agentul de pe
ecran și dă tot spațiul montajului, ca Resolve (pagini Montaj / Noduri / Culoare, `⇧4` / `⇧5` / `⇧6`).

- **Spațiu pentru timeline:** pistele sunt toate vizibile (și cele goale, ca să ai unde trage) și înalte;
  înălțimea se reglează. Monitorul stă în dreapta: fix pentru vertical (ocupă exact cât cere 9:16),
  fereastră plutitoare pentru orizontal (altfel ar fura jumătate din timeline).
- **Navigare de planșă:** zoom ancorat sub cursor, mâna (`⌥` / rotița apăsată), harta de sus. Harta e singurul
  element nou: arată tot montajul și unde ești, ca minimap-ul din editoarele de cod.
- **Nodurile** au o dungă de culoare pe categorie (culoare / detaliu / stil / transformare / mască / compoziție),
  ca în Fusion: culoarea spune ce face nodul, nu decorează. Legăturile spre măști sunt punctate.
- **Umbre** doar pe ce plutește (ferestre, noduri, paleta), pentru că stă deasupra planului de lucru.
- **Viewerul de noduri și de culoare** e un cadru randat de ffmpeg pe server, nu o aproximare în browser:
  ce vezi acolo e ce iese la export.
