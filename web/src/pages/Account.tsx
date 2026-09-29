import { useEffect, useState } from "react";
import { api } from "../api";
import type { LedgerEntry, Me, Pack } from "../types";

interface Props {
  me: Me;
  payment: "ok" | "anulata" | null;
}

const date = (ts: number) =>
  new Date(ts * 1000).toLocaleString("ro-RO", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

export default function Account({ me, payment }: Props) {
  const [packs, setPacks] = useState<Pack[] | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[] | null>(null);
  const [err, setErr] = useState("");
  const [buying, setBuying] = useState("");

  useEffect(() => {
    api.packs().then(setPacks).catch(() => setPacks([]));
  }, []);

  // istoricul se reîncarcă odată cu creditele (după plată, după un export)
  useEffect(() => {
    api.ledger().then(setLedger).catch((e) => setErr(e.message));
  }, [me.credits]);

  const buy = async (id: string) => {
    setErr("");
    setBuying(id);
    try {
      const { url } = await api.checkout(id);
      window.location.href = url;
    } catch (e) {
      setErr((e as Error).message);
      setBuying("");
    }
  };

  return (
    <main className="home account">
      <a href="#/" className="btn sm ghost back">
        ← Proiecte
      </a>
      <h1>
        <span className="tc big">{me.credits}</span> {me.credits === 1 ? "minut rămas" : "minute rămase"}
      </h1>
      <p className="fmt">
        {me.email} · 1 credit = 1 minut început de video exportat la rezoluție finală. Preview-urile sunt gratuite.
      </p>

      {payment === "ok" && (
        <div className="notice">Plata a trecut. Creditele apar aici în câteva secunde, după confirmarea de la Stripe.</div>
      )}
      {payment === "anulata" && <div className="notice warn">Plata a fost anulată. Nu ți s-a luat niciun ban.</div>}

      <h2>Cumpără minute</h2>
      {packs === null ? (
        <div className="working">
          <span className="spinner" /> se încarcă
        </div>
      ) : packs.length === 0 ? (
        <div className="empty">Plățile nu sunt configurate pe acest server (VEDIT_PACKS + Stripe).</div>
      ) : (
        <div className="packs">
          {packs.map((p) => (
            <div className="pack" key={p.id}>
              <b className="tc">{p.credits}</b>
              <span>{p.label}</span>
              {p.price && <span className="price">{p.price}</span>}
              <button className="btn primary sm" disabled={Boolean(buying)} onClick={() => buy(p.id)}>
                {buying === p.id ? "se deschide Stripe…" : "Cumpără"}
              </button>
            </div>
          ))}
        </div>
      )}

      <h2>Istoric</h2>
      {ledger === null ? null : ledger.length === 0 ? (
        <div className="empty">Nicio mișcare încă.</div>
      ) : (
        <table className="ledger">
          <tbody>
            {ledger.map((e, i) => (
              <tr key={i}>
                <td className="tc when">{date(e.ts)}</td>
                <td>{e.reason}</td>
                <td className={`tc delta ${e.delta > 0 ? "plus" : ""}`}>
                  {e.delta > 0 ? "+" : ""}
                  {e.delta}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {err && (
        <div className="toast" onClick={() => setErr("")}>
          {err}
        </div>
      )}
    </main>
  );
}
