// Operații pure pe graful de noduri al unui clip (oglinda lui vedit/nodes.py). Serverul validează tot.
import type { GraphEdge, GraphNode, NodeGraph, NodeSpec } from "./types";

export function defaultGraph(): NodeGraph {
  return {
    nodes: [
      { id: "in", type: "in", params: {}, x: 40, y: 160 },
      { id: "out", type: "out", params: {}, x: 560, y: 160 },
    ],
    edges: [{ src: "in", dst: "out", port: "in" }],
  };
}

export function graphOf(nodes: NodeGraph | null | undefined): NodeGraph {
  return nodes && nodes.nodes.length ? nodes : defaultGraph();
}

export function newNodeId(g: NodeGraph, type: string): string {
  const base = type.replace(/[^a-z]/g, "").slice(0, 8) || "n";
  let k = 1;
  while (g.nodes.some((n) => n.id === `${base}${k}`)) k++;
  return `${base}${k}`;
}

export function paramValue(spec: NodeSpec, n: GraphNode, key: string): number | string {
  return n.params[key] ?? spec.params[key].def;
}

/** Ar crea legătura un ciclu? (src ajunge deja din dst) */
export function wouldCycle(g: NodeGraph, src: string, dst: string): boolean {
  if (src === dst) return true;
  const out: Record<string, string[]> = {};
  g.edges.forEach((e) => (out[e.src] ??= []).push(e.dst));
  const stack = [dst];
  const seen = new Set<string>();
  while (stack.length) {
    const i = stack.pop()!;
    if (i === src) return true;
    if (seen.has(i)) continue;
    seen.add(i);
    stack.push(...(out[i] ?? []));
  }
  return false;
}

/** Leagă src → dst.port; legătura veche de pe același port se înlocuiește. */
export function connect(g: NodeGraph, src: string, dst: string, port: string): NodeGraph {
  if (wouldCycle(g, src, dst)) return g;
  const edges = g.edges.filter((e) => !(e.dst === dst && e.port === port));
  return { ...g, edges: [...edges, { src, dst, port }] };
}

export function disconnect(g: NodeGraph, e: GraphEdge): NodeGraph {
  return { ...g, edges: g.edges.filter((x) => !(x.dst === e.dst && x.port === e.port)) };
}

/** Șterge nodul și, unde se poate, leagă ce intra în el direct la ce ieșea din el. */
export function removeNode(g: NodeGraph, id: string): NodeGraph {
  const n = g.nodes.find((x) => x.id === id);
  if (!n || n.type === "in" || n.type === "out") return g;
  const feed = g.edges.find((e) => e.dst === id && (e.port === "in" || e.port === "bg"));
  const outs = g.edges.filter((e) => e.src === id);
  let edges = g.edges.filter((e) => e.src !== id && e.dst !== id);
  if (feed) edges = [...edges, ...outs.map((e) => ({ ...e, src: feed.src }))];
  return { nodes: g.nodes.filter((x) => x.id !== id), edges };
}

/**
 * Adaugă un nod. Dacă e selectată o legătură sau un nod cu ieșire, noul nod se inserează după el
 * (ca în Fusion: nodul nou intră în lanț, nu rămâne izolat).
 */
export function addNode(g: NodeGraph, type: string, spec: NodeSpec, after: string | null, at?: { x: number; y: number }): { g: NodeGraph; id: string } {
  const id = newNodeId(g, type);
  const base = g.nodes.find((n) => n.id === after) ?? g.nodes.find((n) => n.type === "in")!;
  const pos = at ?? { x: base.x + 180, y: base.y + (spec.inputs.length ? 0 : 120) };
  const node: GraphNode = { id, type, params: {}, x: pos.x, y: pos.y };
  let edges = g.edges;
  if (spec.inputs.length && after) {
    const port = spec.inputs[0] === "bg" ? "bg" : "in";
    const outs = edges.filter((e) => e.src === after);
    edges = [...edges.filter((e) => e.src !== after), { src: after, dst: id, port }, ...outs.map((e) => ({ ...e, src: id }))];
    // nodurile de după se dau puțin la dreapta, ca să nu se suprapună
    const shift = new Set<string>();
    const walk = (i: string) => edges.filter((e) => e.src === i).forEach((e) => !shift.has(e.dst) && (shift.add(e.dst), walk(e.dst)));
    walk(id);
    return { g: { nodes: [...g.nodes.map((n) => (shift.has(n.id) ? { ...n, x: n.x + 180 } : n)), node], edges }, id };
  }
  return { g: { nodes: [...g.nodes, node], edges }, id };
}

export function setParams(g: NodeGraph, id: string, params: Record<string, number | string>): NodeGraph {
  return { ...g, nodes: g.nodes.map((n) => (n.id === id ? { ...n, params: { ...n.params, ...params } } : n)) };
}

export function moveNode(g: NodeGraph, id: string, x: number, y: number): NodeGraph {
  return { ...g, nodes: g.nodes.map((n) => (n.id === id ? { ...n, x, y } : n)) };
}

/** Graful nu schimbă nimic: doar in → out (se salvează ca null, clipul rămâne curat). */
export function isPassthrough(g: NodeGraph): boolean {
  const out = g.nodes.find((n) => n.type === "out");
  const inn = g.nodes.find((n) => n.type === "in");
  return g.nodes.length === 2 && g.edges.length === 1 && g.edges[0].src === inn?.id && g.edges[0].dst === out?.id;
}

// ---------- pagina de culoare: un lanț fix corecție primară → roți → curbe, imediat după intrare ----------
export const COLOR_CHAIN = ["cc_color", "cc_wheels", "cc_curves"] as const;
const CHAIN_TYPE: Record<string, string> = { cc_color: "color", cc_wheels: "wheels", cc_curves: "curves" };

/** Asigură lanțul de culoare (in → cc_color → cc_wheels → cc_curves → ce urma după in). */
export function ensureColorChain(g: NodeGraph): NodeGraph {
  if (COLOR_CHAIN.every((id) => g.nodes.some((n) => n.id === id))) return g;
  const inn = g.nodes.find((n) => n.type === "in")!;
  const missing = COLOR_CHAIN.filter((id) => !g.nodes.some((n) => n.id === id));
  let out = g;
  // inserăm pe rând, fiecare după cel dinainte din lanț (sau după in)
  for (const id of missing) {
    const k = COLOR_CHAIN.indexOf(id);
    const prev = k === 0 ? inn.id : COLOR_CHAIN[k - 1];
    const fake: NodeSpec = { label: "", cat: "", inputs: ["in"], params: {} };
    const r = addNode(out, CHAIN_TYPE[id], fake, prev, { x: inn.x + 180 * (k + 1), y: inn.y - 110 });
    out = {
      nodes: r.g.nodes.map((n) => (n.id === r.id ? { ...n, id } : n)),
      edges: r.g.edges.map((e) => ({ ...e, src: e.src === r.id ? id : e.src, dst: e.dst === r.id ? id : e.dst })),
    };
  }
  return out;
}
