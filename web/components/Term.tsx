import { getCatalog } from "@/lib/catalog";

/**
 * A metric name that shows its definition and formula on hover or focus
 * (DESIGN.md: "Definitions visible everywhere"). The text comes from metrics.yml.
 */
export async function Term({ metric, children }: { metric: string; children?: React.ReactNode }) {
  const def = (await getCatalog()).get(metric);
  const label = children ?? def?.label ?? metric;
  if (!def) return <>{label}</>;
  return (
    <span className="term" tabIndex={0} aria-describedby={`term-${metric}`}>
      {label}
      <span className="term-pop" role="tooltip" id={`term-${metric}`}>
        {def.description}
        <code>{def.formula}</code>
      </span>
    </span>
  );
}
