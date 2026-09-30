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
