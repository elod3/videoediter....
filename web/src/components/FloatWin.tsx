import { useEffect, useRef, useState } from "react";

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface Props {
  /** cheia sub care se ține poziția (localStorage), ca fereastra să rămână unde ai lăsat-o */
  id: string;
  title: React.ReactNode;
  initial: () => Box;
  minW?: number;
  minH?: number;
  /** raportul lățime / înălțime al conținutului: la redimensionare fereastra îl păstrează */
  aspect?: number;
  /** înălțimea ocupată de antet și bara de jos, care nu intră în raport */
  chrome?: number;
  actions?: React.ReactNode;
  onClose?: () => void;
  children: React.ReactNode;
}

// ultima fereastră atinsă vine deasupra celorlalte
let topZ = 20;

function load(id: string): Box | null {
  try {
    const b = JSON.parse(localStorage.getItem(`vedit_win_${id}`) ?? "null");
    return b && [b.x, b.y, b.w, b.h].every((v) => typeof v === "number") ? b : null;
  } catch {
    return null;
  }
}

/** Fereastră plutitoare în interiorul părintelui (position: relative): o muți de antet, o redimensionezi din colț. */
export default function FloatWin({ id, title, initial, minW = 220, minH = 160, aspect, chrome = 0, actions, onClose, children }: Props) {
  const [box, setBox] = useState<Box>(() => load(id) ?? initial());
  const [z, setZ] = useState(() => ++topZ);
  const ref = useRef<HTMLDivElement>(null);
  const op = useRef<{ kind: "move" | "size"; x0: number; y0: number; b: Box } | null>(null);

  // rămâne în părinte când acesta se micșorează (ieșirea din ecran complet, fereastra browserului)
  useEffect(() => {
    const parent = ref.current?.parentElement;
    if (!parent) return;
    const fit = () =>
      setBox((b) => {
        const pw = parent.clientWidth;
        const ph = parent.clientHeight;
        const w = Math.min(b.w, pw);
        const h = Math.min(b.h, ph);
        return { w, h, x: Math.min(Math.max(0, b.x), pw - w), y: Math.min(Math.max(0, b.y), ph - h) };
      });
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(parent);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(`vedit_win_${id}`, JSON.stringify(box));
    } catch {
      /* fără storage: poziția ține doar cât e pagina deschisă */
    }
  }, [id, box]);

  const begin = (kind: "move" | "size") => (e: React.PointerEvent) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest("button, input, select")) return;
    e.preventDefault();
    op.current = { kind, x0: e.clientX, y0: e.clientY, b: box };
    const parent = ref.current!.parentElement!;
    const move = (ev: PointerEvent) => {
      const o = op.current!;
      const dx = ev.clientX - o.x0;
      const dy = ev.clientY - o.y0;
      const pw = parent.clientWidth;
      const ph = parent.clientHeight;
      if (o.kind === "move") {
        setBox({ ...o.b, x: Math.min(Math.max(0, o.b.x + dx), pw - o.b.w), y: Math.min(Math.max(0, o.b.y + dy), ph - o.b.h) });
      } else {
        // colțul din stânga-jos: fereastra stă de obicei în dreapta, deci crește spre stânga
        let w = Math.min(Math.max(minW, o.b.w - dx), o.b.x + o.b.w);
        let h = Math.max(minH, o.b.h + dy);
        if (aspect) h = w / aspect + chrome;
        if (o.b.y + h > ph) {
          h = ph - o.b.y;
          if (aspect) w = (h - chrome) * aspect;
        }
        setBox({ x: o.b.x + o.b.w - w, y: o.b.y, w, h });
      }
    };
    const up = () => {
      op.current = null;
      window.removeEventListener("pointermove", move);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
  };

  return (
    <div className="fwin" ref={ref} style={{ left: box.x, top: box.y, width: box.w, height: box.h, zIndex: z }} onPointerDownCapture={() => z !== topZ && setZ(++topZ)}>
      <div className="fwin-head" onPointerDown={begin("move")}>
        <span className="fwin-title">{title}</span>
        {actions}
        {onClose && (
          <button className="fwin-x" onClick={onClose} aria-label="închide" title="închide">
            ×
          </button>
        )}
      </div>
      <div className="fwin-body">{children}</div>
      <span className="fwin-size" onPointerDown={begin("size")} title="trage ca să schimbi mărimea" />
    </div>
  );
}
