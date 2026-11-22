// Źródła danych z provenance (styl: tabela .tbl): źródło, stan, dane do, czas lub tryb, licencja, uwagi.
const STATUS = {
  ok: ["brak", "działa"],
  partial: ["na_granicy", "częściowo"],
  timeout: ["zagrozenie", "nie odpowiedziało"],
  error: ["zagrozenie", "błąd"],
  empty: ["", "brak danych"],
};

export default function Sources({ provenance }) {
  if (!provenance?.length) return null;
  return (
    <div className="scrollx">
      <table className="tbl">
        <thead><tr><th>Źródło</th><th>Stan</th><th>Dane do</th><th>Licencja</th></tr></thead>
        <tbody>
          {provenance.map((p) => {
            const [cls, label] = STATUS[p.status] || ["", p.status];
            const how = p.mode === "constant" ? "stała" : p.mode === "cache" ? "z zapisu" : `${(p.latency_ms / 1000).toFixed(1).replace(".", ",")} s`;
            return (
              <tr key={p.source}>
                <td>{p.source}</td>
                <td><span className={`pill ${cls}`}>{label}</span><div className="small muted">{how}</div></td>
                <td>{p.data_until || "—"}</td>
                <td className="small">{p.licence}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
