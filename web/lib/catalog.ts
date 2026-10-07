import { cache } from "react";

import { api, type Catalog, type CatalogMetric } from "./api";

/** The metric catalogue (from semantic/metrics.yml), fetched once per request. */
export const getCatalog = cache(async (): Promise<Map<string, CatalogMetric>> => {
  try {
    const catalog = await api<Catalog>("/v1/metrics");
    return new Map(catalog.metrics.map((m) => [m.name, m]));
  } catch {
    return new Map();
  }
});
