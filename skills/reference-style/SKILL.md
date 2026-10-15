---
name: reference-style
description: Editează în stilul unui clip de referință dat de client (ritm, hook, format, culoare, subtitrări). Folosește când un fișier e marcat [REFERINȚĂ] în lista de asset-uri, sau când clientul zice „ca în clipul ăsta”, „în stilul lui X”, „vreau să arate așa”, „aceeași culoare / același vibe”.
---

# Stil după referință

Referința e un **model de măsurat**, nu material de montaj. Nu pune niciodată un clip `[REFERINȚĂ]` în timeline.

## 1. Măsoară referința (nu o descrie din imaginație)

1. `reference_analyze()` → ritm (tăieturi/min, shot median, tăieturi în primele 3 s), culoare, audio, format.
   Ritmul e estimat din schimbările de imagine: jump cut-urile pe același fundal pot fi subnumărate,
   așa că tratează cifra ca limită de jos.
2. `frames_look(asset=<referința>, cols=4, rows=2)`: deschide imaginea și notează ce NU se măsoară automat:
   - subtitrări: da/nu, poziție (sus/mijloc/jos), câte cuvinte, majuscule, cuvânt evidențiat?
   - text de hook în primele secunde? zoom-uri / punch-in? B-roll peste vorbire?
3. Scrie un „profil de stil” de 4-6 rânduri cu cifrele de mai sus. Pe el îl urmezi, nu pe cererea vagă.

## 2. Traduce profilul în decizii

| Ce măsori în referință | Ce faci |
|---|---|
| shot median < 2 s | `cut_silences(min_silence=0.3, padding=0.06)` + `cut_words` pe toate umpluturile + `auto_reframe(punch_in=0.15)` |
| shot median 2-4 s | `cut_silences(min_silence=0.5)` + punch-in pe cam o tăietură din două |
| shot median > 4 s | `cut_silences(min_silence=0.8)`, fără punch-in |
| ≥ 2 tăieturi în primele 3 s | deschide cu cea mai tare frază (`keep_words` / `clip_move`), taie des la început |
| format 9:16 / 1:1 / 4:5 | același `timeline_format` + `auto_reframe` |
| subtitrări 1-3 cuvinte, mari | `captions_add(style="bold_center")`; cu cuvânt evidențiat → `karaoke`; jos, frază întreagă → `classic_bottom` |
| culoare | `color_match(strength=0.8)`; dacă referința e foarte stilizată și sursa arată ciudat, coboară la 0.5-0.6 |

## 3. Buclă de verificare (obligatorie)

1. `render(preview=true)` → `style_compare()`.
2. Fiecare sfat din `tips` numește tool-ul care mută acul. Aplică-l, randează preview din nou, compară din nou.
3. Maxim 3 bucle. Oprește-te când sfaturile rămase sunt doar „se judecă vizual”.
4. `frames_look(asset="render:preview")` pus lângă referință: aceeași poziție a subtitrărilor, aceeași încadrare?

## 4. Culoare fără referință

`color_grade(preset=...)`: `cald`, `rece`, `contrast`, `desaturat`, `alb_negru`, `cinematic`, `luminos`,
sau reglaje fine (`exposure`, `contrast`, `saturation`, `temperature`, `tint`, `teal_orange`).
Se pot combina cu `color_match`: potrivirea se face întâi, reglajele se aplică peste ea.

## Ce NU poți copia încă (spune-i clientului, nu promite)

B-roll peste vorbire (există o singură pistă video), tranziții, speed ramp, zoom animat în interiorul unui shot,
efecte sonore, montaj pe beat-ul muzicii. Dacă referința se bazează pe astea, spune explicit ce ai putut
reproduce și ce nu.
