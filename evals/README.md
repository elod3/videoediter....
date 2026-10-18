# Evaluări pe clipuri reale

Fiecare subfolder e un caz: `case.json` + fișierele lui (clipurile NU se urcă în git; pune-le local).
Formatul complet e descris în `vedit/evals.py`.

```bash
cp ~/Videos/vlog-real.mp4 evals/exemplu-vlog-tiktok/vlog.mp4
vedit-eval evals/ --runner claude-code        # sau scripted / llm
cat eval-report/report.md
```

Cum le folosești ca să îmbunătățești skill-urile:
1. Strânge 10-30 de clipuri reale, fiecare cu cererea și așteptările lui.
2. Rulează evaluarea, notează ce pică.
3. Schimbă UN lucru într-un skill (un prag, o regulă), rulează din nou, compară rapoartele.
