// Jurnal real: primul job rulat de Claude Code pe toolkit (podcast de test, 9 s, 25 fps).
const SAMPLE_LOG: [string, string][] = [
  ["media_analyze", "a0 · 00:00:09:00 · −12.1 LUFS"],
  ["cut_silences", "nicio pauză peste 0.4 s, nimic de tăiat"],
  ["timeline_format", "1080×1920 · crop"],
  ["auto_reframe", "S0 cx 0.19 → S1 cx 0.80 la 00:00:03:05"],
  ["render", "preview 540×960 · 00:00:09:00"],
  ["qa_check", "ok · −14.0 LUFS · fără cadre negre"],
];

export default function EdlSample() {
  return (
    <figure className="edl" style={{ margin: 0 }}>
      <div className="edl-head">
        <span>jurnal de montaj · podcast-demo</span>
        <span>25 fps</span>
      </div>
      {SAMPLE_LOG.map(([tool, res], i) => (
        <div className="edl-row" key={tool}>
          <span className="n">{String(i + 1).padStart(3, "0")}</span>
          <span>{tool}</span>
          <span className="res">{res}</span>
        </div>
      ))}
      <div className="edl-foot">
        Claude Code · 6 pași · <b>17 s</b>
      </div>
    </figure>
  );
}
