/* Runtime-ul comun al blocurilor de motion.
 *
 * Fiecare bloc definește `function build(V)` și pune animațiile pe V.tl (o cronologie GSAP OPRITĂ).
 * Randatorul (vedit/motion/engine.py) cheamă window.__vedit.seek(t) pentru fiecare cadru și face captura.
 * Parametrii vin din JSON (#vedit-data) și se pun în pagină DOAR ca text (V.text), niciodată ca HTML.
 */
(function () {
  "use strict";
  window.__vedit = { ready: false, seek: function () { return false; } };
  try {
    var D = JSON.parse(document.getElementById("vedit-data").textContent);
    var P = D.params || {}, S = D.style || {}, W = D.width, H = D.height, DUR = D.duration;
    // 1u = 1% din latura mică; pe vertical +20%, ca textul să se citească pe telefon (acolo cadrul e îngust)
    var u = Math.min(W, H) / 100 * (H > W ? 1.2 : 1);
    var root = document.documentElement.style;
    var c = S.colors || {};
    var vars = {
      "--W": W + "px", "--H": H + "px", "--u": u + "px",
      "--font-display": S.font_display || "Montserrat", "--font-body": S.font_body || "Montserrat",
      "--font-accent": S.font_accent || S.font_display || "Montserrat",
      // tipografia în 3 registre (stack_title, orbit_words): cuvântul uriaș condensat + scrisul de mână
      "--font-huge": S.font_huge || "League Gothic", "--font-script": S.font_script || "Kaushan Script",
      "--w-display": S.weight_display || 800, "--w-body": S.weight_body || 500,
      "--stretch-display": (S.stretch_display || 100) + "%", "--stretch-body": (S.stretch_body || 100) + "%",
      "--case": S.text_case || "none", "--track": (S.tracking || 0) + "em",
      "--lh-display": S.line_height || 1.02,
      "--ink": c.ink || "#ffffff", "--muted": c.muted || "rgba(255,255,255,.7)",
      // textul pus direct pe filmare (nu pe panou): la stilurile cu panouri deschise rămâne alb
      "--ink-free": c.ink_free || c.ink || "#ffffff", "--muted-free": c.muted_free || c.muted || "rgba(255,255,255,.75)",
      "--accent": c.accent || "#f5c542", "--panel": c.panel || "rgba(14,16,20,.86)",
      "--bg": c.bg || "#0b0d10", "--bg2": c.bg2 || "#16191f", "--line": c.line || "rgba(255,255,255,.12)",
      "--radius": (S.radius == null ? 2.2 : S.radius) * u + "px", "--shadow": S.shadow == null ? 0.35 : S.shadow,
      "--grain": S.grain || 0
    };
    for (var k in vars) root.setProperty(k, vars[k]);

    if (S.panels === false) document.getElementById("stage").classList.add("nopanel");
    // blocul în spatele persoanei se randează în două treceri: „back” fără elementele .fg, „front” doar cu ele
    if (P._layer === "back" || P._layer === "front") document.documentElement.classList.add("layer-" + P._layer);
    gsap.registerPlugin(SplitText, ScrambleTextPlugin, DrawSVGPlugin, CustomEase);
    // curbele vin din stil; implicit un „expo out” moale: pornește repede, se așază lent
    CustomEase.create("vIn", S.ease_in || "0.16,1,0.3,1");
    CustomEase.create("vOut", S.ease_out || "0.7,0,0.84,0");
    CustomEase.create("vPop", S.ease_pop || "0.34,1.56,0.64,1");

    var tl = gsap.timeline({ paused: true, defaults: { ease: "vIn", duration: S.dur_in || 0.7 } });
    var outDur = S.dur_out == null ? 0.45 : S.dur_out;

    var scene = P._scene || {};
    var V = {
      P: P, S: S, W: W, H: H, DUR: DUR, u: u, tl: tl, vertical: H > W,
      // ce e sub bloc (Motion.scene): fața [x, y, w, h] în cadru (0..1) sau null, luminozitatea pe 3 benzi
      face: scene.face && scene.face.length === 4 ? { x: scene.face[0], y: scene.face[1], w: scene.face[2], h: scene.face[3] } : null,
      luma: scene.luma || null,
      // textul liber pus pe zona dintr-o bandă deschisă devine închis (altfel alb pe alb nu se citește)
      autoInk: function (e, yFrac) {
        if (!V.luma) return;
        var b = V.luma[Math.min(2, Math.max(0, Math.floor((yFrac == null ? .5 : yFrac) * 3)))];
        if (b > 0.62) e.classList.add("on-light");
      },
      outAt: Math.max(0.3, DUR - outDur), outDur: outDur, noExit: false,
      blur: (S.blur_in == null ? 1.2 : S.blur_in) * u, stagger: S.stagger == null ? 0.06 : S.stagger,
      img: function (key) { return D.images && D.images[key] ? D.images[key] : null; },
      el: function (tag, cls, parent) {
        var e = document.createElement(tag || "div");
        if (cls) e.className = cls;
        (parent || document.getElementById("stage")).appendChild(e);
        return e;
      },
      text: function (e, s) { e.textContent = s == null ? "" : String(s); return e; },
      // cuvintele, fiecare într-un <span>; cele din `marks` primesc subliniere / marker animat
      words: function (e, s, marks, kind) {
        marks = (marks || []).map(function (m) { return String(m).toLowerCase().replace(/[^\p{L}\p{N}]/gu, ""); });
        var out = [];
        String(s || "").split(/\s+/).filter(Boolean).forEach(function (w, i, arr) {
          var span = document.createElement("span");
          span.style.display = "inline-block";
          span.style.whiteSpace = "pre";
          var clean = w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
          var marked = marks.indexOf(clean) >= 0;
          var inner = document.createElement("span");
          inner.textContent = w;
          if (marked) {
            span.className = kind === "line" ? "hl-line" : kind === "color" ? "hl" : "hl-mark";
            span.style.position = "relative"; span.style.zIndex = 0;
            if (kind !== "color") { var m = document.createElement("span"); m.className = "mark"; span.appendChild(m); }
          }
          span.appendChild(inner);
          e.appendChild(span);
          if (i < arr.length - 1) e.appendChild(document.createTextNode(" "));
          out.push({ el: span, word: inner, marked: marked, mark: span.querySelector(".mark") });
        });
        return out;
      },
      // apariția standard: blur -> clar, de jos, cu fade (semnătura stilurilor „premium”)
      reveal: function (targets, at, opts) {
        opts = opts || {};
        tl.fromTo(targets,
          { opacity: 0, y: opts.y == null ? 2.2 * u : opts.y, filter: "blur(" + (opts.blur == null ? V.blur : opts.blur) + "px)",
            scale: opts.scale || 1 },
          { opacity: 1, y: 0, filter: "blur(0px)", scale: 1, duration: opts.duration || S.dur_in || 0.7,
            stagger: opts.stagger == null ? V.stagger : opts.stagger, ease: opts.ease || "vIn" }, at || 0);
      },
      marks: function (items, at) {
        items.filter(function (w) { return w.mark; }).forEach(function (w, i) {
          tl.fromTo(w.mark, { scaleX: 0 }, { scaleX: 1, duration: 0.5, ease: "vIn" }, (at || 0.4) + i * 0.12);
        });
      },
      // poziția obiectului urmărit la timpul t (0..1 în cadru); null fără urmărire
      track: function (t) {
        var p = P._track || [];
        if (!p.length) return null;
        if (t <= p[0][0]) return { x: p[0][1], y: p[0][2] };
        for (var i = 0; i < p.length - 1; i++) {
          if (t <= p[i + 1][0]) {
            var u = (t - p[i][0]) / Math.max(p[i + 1][0] - p[i][0], 1e-6);
            return { x: p[i][1] + (p[i + 1][1] - p[i][1]) * u, y: p[i][2] + (p[i + 1][2] - p[i][2]) * u };
          }
        }
        return { x: p[p.length - 1][1], y: p[p.length - 1][2] };
      },
      onTrack: null,
      // potrivește textul în cutie: micșorează până încape (fără tăieturi pe margini)
      fit: function (e, maxW, maxH, minPx) {
        var fs = parseFloat(getComputedStyle(e).fontSize);
        var guard = 60;
        while (guard-- > 0 && fs > (minPx || 10) && (e.scrollWidth > maxW + 1 || (maxH && e.scrollHeight > maxH + 1))) {
          fs *= 0.95; e.style.fontSize = fs + "px";
        }
        return fs;
      }
    };
    window.V = V;

    var go = function () {
      try {
        if (typeof window.build !== "function") throw new Error("blocul nu are build(V)");
        window.build(V);
        if (!V.noExit) {
          tl.to("#stage", { opacity: 0, filter: "blur(" + (0.8 * u) + "px)", y: -1.2 * u, duration: outDur, ease: "vOut" },
            V.outAt);
        }
        tl.set({}, {}, DUR); // cronologia ține exact cât blocul
        var path = P._track || [];
        var stage = document.getElementById("stage");
        window.__vedit.seek = function (t) {
          tl.seek(Math.min(Math.max(t, 0), DUR), false);
          if (path.length) {  // blocul urmărește obiectul: totul se mută cu cât s-a mutat obiectul de la început
            var p = V.track(t);
            if (V.onTrack) V.onTrack(p); else gsap.set(stage, { x: (p.x - path[0][1]) * W, y: (p.y - path[0][2]) * H });
          }
          return true;
        };
        window.__vedit.ready = true;
      } catch (e) { window.__vedit_error = String(e && e.stack || e); }
    };
    // fonturile se încarcă leneș (abia când sunt folosite): blocul și-ar măsura textul cu fontul de rezervă.
    // Le cerem pe toate ale stilului înainte de build, ca V.fit și măsurătorile să vadă fontul real.
    var want = [[S.font_display, S.weight_display], [S.font_body, S.weight_body], [S.font_accent, 400],
                [S.font_huge || "League Gothic", 400], [S.font_script || "Kaushan Script", 400], ["Montserrat", 900],
                ["Montserrat", 600]];
    var loads = document.fonts ? want.filter(function (f) { return f[0]; }).map(function (f) {
      return document.fonts.load((f[1] || 400) + " 40px \"" + f[0] + "\"").catch(function () {});
    }) : [];
    Promise.all(loads).then(function () { return document.fonts ? document.fonts.ready : null; }).then(go);
  } catch (e) { window.__vedit_error = String(e && e.stack || e); }
})();
