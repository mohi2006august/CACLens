import type { Metadata } from "next";

import { ErrorState, PageHead } from "@/components/ui";
import { api, type Catalog } from "@/lib/api";

export const metadata: Metadata = { title: "Definitions" };

export default async function DefinitionsPage() {
  let catalog: Catalog;
  try {
    catalog = await api<Catalog>("/v1/metrics");
  } catch (error) {
    return (
      <>
        <PageHead title="Definitions" />
        <ErrorState error={error} />
      </>
    );
  }
  return (
    <>
      <PageHead
        title="Metric definitions"
        subtitle="Every number in CACLens comes from these definitions in semantic/metrics.yml. Dashboards, alerts and Q&A share them."
      />
      <section className="card" style={{ marginBottom: 16 }}>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Formula</th>
                <th>Definition</th>
                <th>Sliceable by</th>
              </tr>
            </thead>
            <tbody>
              {catalog.metrics.map((m) => (
                <tr key={m.name} id={m.name}>
                  <td>
                    <strong>{m.label}</strong>
                    <div className="mono muted" style={{ fontSize: 11 }}>
                      {m.name}
                    </div>
                  </td>
                  <td className="mono" style={{ fontSize: 12 }}>
                    {m.formula}
                  </td>
                  <td className="secondary">
                    {m.description}
                    {m.fully_loaded_variant && (
                      <div className="muted" style={{ fontSize: 12 }}>
                        Fully loaded toggle → <a href={`#${m.fully_loaded_variant}`}>{m.fully_loaded_variant}</a>
                      </div>
                    )}
                  </td>
                  <td className="muted" style={{ fontSize: 12 }}>
                    {m.dimensions.join(", ")} · finest grain {m.min_grain}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <h2 style={{ marginBottom: 8 }}>Dimensions</h2>
        <table className="data">
          <tbody>
            {catalog.dimensions.map((d) => (
              <tr key={d.name}>
                <td style={{ width: 200 }}>
                  <strong>{d.label}</strong>
                  <div className="mono muted" style={{ fontSize: 11 }}>
                    {d.name}
                  </div>
                </td>
                <td className="secondary">
                  {d.description}
                  {d.values.length > 0 && d.values.length <= 12 && (
                    <div className="mono muted" style={{ fontSize: 11, marginTop: 4 }}>
                      {d.values.join(" · ")}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
