# Tutorial vedit: de la zero la primul clip editat de AI

Ghid practic, pas cu pas. Cererile din casetele de cod le copiezi exact așa în Claude Code.

---

## 1. Ce îți trebuie (o singură dată, ~10 minute)

Pe Arch:

```bash
sudo pacman -S ffmpeg python nodejs npm git
git clone https://github.com/elod3/videoediter.... vedit && cd vedit
python -m venv .venv && source .venv/bin/activate
make install        # instalează tot: editorul, whisper (transcriere), vocea AI, site-ul
```

Mai ai nevoie de **Claude Code** logat cu abonamentul tău (`claude` în terminal).

> La primul clip se descarcă automat câteva modele: whisper (transcriere), vocea românească,
> decuparea persoanei. Durează câteva minute o singură dată; după, merge offline.

---

## 2. Primul test (5 minute)

```bash
make demo           # construiește în demo/: vlog, podcast cu 3 camere, piesă pe beat, B-roll, poze
claude              # pornește Claude Code în folderul proiectului
```

În Claude Code, scrie:

```
editează demo/vlog.mp4 pentru TikTok: fără pauze, 9:16, cuvinte-cheie, efecte sonore
```

Ce se întâmplă:
1. **Agentul își citește skill-urile**, adică instrucțiunile de editor.
2. **Transcrie clipul** cu whisper.
3. **Taie pauzele** pe cuvinte, nu în mijlocul lor.
4. **Trece pe 9:16** și încadrează pe față.
5. **Pune subtitrări** cu cuvintele-cheie colorate și efecte sonore discrete.
6. **Randează un preview**, se uită la cadre și repară ce nu e ok.
7. **Randează finalul**, rulează QA și îți spune ce a făcut.

Rezultatul: `vedit_projects/<proiect>/renders/final.mp4`.

> Claude Code îți cere voie la primul tool vedit. Alege „allow always” pentru `mcp__vedit`.

---

## 3. Cum vorbești cu agentul

**Bine:** spui platforma, durata, stilul și ce nu vrei.

```
pentru Reels, maxim 40 de secunde, păstrează partea cu povestea de la început,
subtitrări stil Hormozi, fără muzică
```

**Prea vag (merge, dar agentul ghicește):**

```
fă-l viral
```

Poți itera oricât, în aceeași conversație:

```
mai scurt, sub 30 de secunde
scoate efectele sonore
titlul să fie în engleză
anulează ultimul pas
```

---

## 4. Rețete: ce poți cere

### Vlog / talking head (o persoană la cameră)
```
editează ~/Videos/vlog.mp4 pentru TikTok: taie pauzele și bâlbele, 9:16, stil Hormozi
```
```
fundalul din spatele meu să fie încețoșat, ca în mod portret
```
```
la început un titlu mare care trece prin spatele meu: „3 GREȘELI”
```

### Shorts dintr-un video lung (podcast, stream, webinar)
```
din ~/Videos/podcast.mp4 fă 3 shorts de 30-45 de secunde cu cele mai bune momente
```

### Podcast cu mai multe camere
```
am filmat cu 3 camere: wide.mp4 (amândoi), ana.mp4, mihai.mp4.
fă varianta de YouTube: sincronizează-le, schimbă camera pe cine vorbește,
lower third cu numele lor
```

### Faceless (fără să apari tu)
```
fă un TikTok faceless de ~40 de secunde despre „5 greșeli la primul apartament”,
voce în română, cu pozele din ~/Poze/apartament
```
Agentul scrie scriptul, generează vocea (AI local, gratuit), pune pozele cu mișcare lentă și subtitrări.
Cu vocea ta: urci o înregistrare audio și spui „folosește vocea din voce.m4a”.

### În stilul altui clip
```
editează vlog.mp4 în stilul lui referinta.mp4 (ritm, format, culoare)
```

### Motion graphics
```
pune numele meu (Elod, fondator vedit) când apar prima dată,
un număr care crește când zic de 10.000 de clienți și un îndemn la final
```

### Muzică și B-roll
```
pune muzica.mp3 sub voce și B-roll din clipurile broll1.mp4, broll2.mp4 peste părțile explicative
```
```
montaj pe beat cu piesa.mp3 din toate clipurile de la eveniment
```

### Altă limbă, cenzură, confidențialitate
```
fă o variantă în engleză cu dublaj AI și subtitrări în engleză
```
```
cenzurează înjurăturile cu bip
```
```
blur pe fețele trecătorilor și pe numărul mașinii de la secunda 12
```

### Livrare
```
exportă pentru TikTok, Reels și YouTube Shorts, plus subtitrări .srt
thumbnail stil YouTube cu titlul „AM GREȘIT”
capitole pentru YouTube
```

### Look-uri gata făcute (rețete)
| Spui | Primești |
|---|---|
| „stil Hormozi” | subtitrări mari, cuvinte-cheie galbene cu pop, punch-in pe ideile tari, efecte sonore |
| „stil MrBeast” | un cuvânt pe ecran cu pop, punch-in des, culori vii, efecte |
| „stil TikTok” | text pe casetă, curat |
| „stil podcast” | subtitrări clasice jos, culoare per vorbitor |
| „stil cinematic” | culori teal & orange, subtitrări discrete |

---

## 5. Site-ul (ce vor folosi clienții)

```bash
make dev            # site pe http://127.0.0.1:5173 (API pe :8000)
```

1. **Creezi un proiect** și urci clipurile (video, poze, muzică).
2. **În dreapta ai patru panouri:**
   - **agent:** scrii ce vrei, iar fiecare pas apare în jurnal, numerotat;
   - **text:** transcriptul; selectezi cuvinte și le tai direct din video (ca în Descript);
   - **livrare:** export pe platforme, subtitrări .srt, capitole, thumbnail;
   - **brand:** logo, culori, font. „Salvează ca kit” și îl ai în toate proiectele.
3. **Jos e timeline-ul** cu pistele V1 (clipuri), V2 (B-roll), GFX (grafice), SUB (subtitrări), A2 (muzică),
   A3 (voce), SFX. Clic pe un clip ca să schimbi tranziția, zoom-ul, viteza sau efectele.
4. **„Anulează ultimul pas”** anulează orice modificare, a ta sau a agentului.

Agentul din site folosește tot Claude Code-ul tău (`VEDIT_RUNNER=claude-code`), deci merge pe abonament.

---

## 6. Când ceva nu merge

| Problema | Ce faci |
|---|---|
| „nu pot descărca modelul / vocea” | verifică internetul; se descarcă o singură dată |
| transcriere lentă | normal la primul rulaj pe clipuri lungi; e în cache după |
| încadrarea taie fața | „încadrează mai bine pe față” sau „fundal încețoșat în loc de crop” (fill blur) |
| subtitrare cu nume greșit | „corectează: w12 e Mihai” sau spune doar „numele e Mihai, nu Mihal” |
| agentul zice REFUZAT (securitate) | o limită de siguranță (alt proiect, fișier din afara proiectului); e voit |
| randarea durează | clipurile lungi 4K pot dura câteva minute; preview-ul e rapid |

Dacă agentul greșește ceva, spune-i exact ce nu-ți place. Lucrează pe același timeline, cu undo.

Ca să testezi totul sistematic (scenarii, ce să verifici, ce să filmezi), vezi [TESTARE.md](TESTARE.md).

---

## 7. Când treci la clienți

- **Deploy pe VPS:** `docs/DEPLOY.md` (Docker + HTTPS automat).
- **Conturi și plăți:** `VEDIT_AUTH=on`, pachetele în `VEDIT_PACKS`, cheile Stripe. 1 credit = 1 minut exportat;
  preview-urile sunt gratuite.
- **Agentul pentru clienți:** nu abonamentul tău, ci un model prin API (`VEDIT_RUNNER=llm`, vezi README).
- **Suport:** `vedit-admin users`, `vedit-admin credits email 10 "bonus"`, `vedit-admin reset-password email`.

**Ce să vinzi întâi:** clipuri scurte din podcast-uri și vlog-uri, pentru creatori mici și firme locale. Se face des,
e repetitiv și plătesc lunar. Arată-le un înainte / după pe clipul lor și încasezi primul pachet.
