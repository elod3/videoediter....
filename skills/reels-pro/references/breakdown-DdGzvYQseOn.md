# Breakdown: DdGzvYQseOn (Milad Aslani, showreel 2x2, 9,45 s, 1080x1920, 30 fps)

NU e un reel cu vorbitor. E un portofoliu: ecranul e o grilă 2x2 (fiecare panou 540x960), patru mini-spoturi simultane,
cu un buton rotund cu „A” în centru. Util ca bibliotecă de LIMBAJ de motion, nu ca structură de montaj pentru client.

## Ce arată fiecare panou (la 10 fps)
- **Stânga-sus:** afiș „Aslani” (condensat ÎNALT, degrade translucid) peste un astronaut pe pajiște; text mic „Motion
  without Limits” sus. Apoi „Consistency is the Key Here” (condensat negru + cheie aurie 3D) pe alb cu arc de
  cerc și puncte; apoi un logo sneaker „Air Jordan” cu buze/ pantof, script roșu „Jordan” sub „Air” (condensat),
  „is a Multibillion dollar Brand” + „$$$” gri; la final „We've already helped”.
- **Dreapta-sus:** UI de player muzical verde (Spotify-like): „Play me a bunch of stuff” tastat, cântece în listă,
  poza vorbitorului în colț, buton verde. Apoi fundal roșu→albastru cu panou V alb: „Every day your business remains
  invisible”, „someone chooses a competitor” (cuvântul-cheie bold, restul subțire).
- **Stânga-jos:** widget „Performance 48°” (sticlă mată + glow verde) construit din pixeli care se adună (0.0-0.4 s),
  apoi „isn't a Luxury”; apoi carduri „advantage / peak performance” cu o placă de bază, SSD, CPU: culoarea
  panoului se schimbă verde → lime → albastru ca ACCENTUL să urmeze obiectul. Apoi „You don't have to become an
  influencer” (gradient albastru) și „We'll match you with a creator” cu 6 avatare care orbitează.
- **Dreapta-jos:** BMW E30 M3 galben „IT'S BMV”: litere condensate înalte „E30 M3” negre pe galben, mașina vine,
  se rotește, devine „NOT BMW” (mașina văzută de sus derapează, cu dâră); „Bayerische” pe pastilă neagră;
  siluetă albă a unui om în palton lung; apoi soare roșu + figură B/N „BECAUSE YOU JUST MADE THE …”; „AE / Editing
  isn't just Cutting” pe fundal B/N cu katana și stropi roșii.

## Reguli extrase
1. O idee per scenă, 1,5-2,5 s. Fiecare cuvânt-cheie are un obiect care îl ILUSTREAZĂ (cheie, mașină, soare, katana).
2. Registre: condensat înalt pentru titlu (1 cuvânt), script roșu pentru accent mic, sans mic pentru explicație.
   Cuvântul-cheie într-o frază: bold, restul light („someone chooses a **competitor**”, „become an **influencer**”).
3. Culoarea scenei se schimbă pe parcurs (roșu → albastru; verde → lime → albastru) = progres fără tăietură.
4. Intrările sunt construcții din particule/pixeli (widget din blocuri verzi), nu fade.
5. Totul pe fundal DE CULOARE plină sau B/N + UN accent (galben pe portocaliu, roșu pe B/N). Fără 3 accente.
6. Carduri/obiecte au umbră moale + glow (o aură în culoarea accentului) și rotație mică.

## Cum se folosește în vedit
- Pentru un client: o scenă de explicație de 2 s cu `stack_title` (cuvânt condensat + accent script) pe `background`
  color plin; schimbarea de culoare a accentului: două `motion_add` consecutive cu `style`/`palette` diferit
  (limitare: vezi GAPS.md, #6).
- UI de player, widget „Performance”, avatare care orbitează: nu există blocuri (GAPS.md, #8).
- NU copia panourile (sunt lucrări de portofoliu ale altui creator; folosește doar tehnica).
