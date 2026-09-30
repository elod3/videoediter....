Fonturi pentru subtitrările randate (libass le încarcă prin `fontsdir`, deci nu depind de sistem).

- `ArchivoBlack-Regular.ttf`: stilurile bold_center și karaoke (short-form)
- `Archivo-Regular.ttf`: stilul classic_bottom (instanță statică generată cu fontTools din fontul variabil, pe care libass nu îl recunoaște)

Ambele sunt sub SIL Open Font License 1.1 (`OFL.txt`), din github.com/google/fonts.
Pentru brandul unui client: `brand_captions(font_path=...)` copiază fontul în `<proiect>/brand/fonts/` și citește
numele familiei; la randare fonturile de aici și cel al brandului se adună într-un `fontsdir` per randare.
