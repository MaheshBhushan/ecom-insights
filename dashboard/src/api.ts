export interface Filters {
  start?: string;
  end?: string;
  category: string[];
  country: string[];
  status: string[];
}

export interface Options {
  categories: string[];
  countries: string[];
  statuses: string[];
  min_date: string | null;
  max_date: string | null;
}

export interface Summary {
  revenue: number;
  orders: number;
  customers: number;
  units: number;
  avg_order_value: number;
}

export interface MonthRevenue {
  month: string;
  revenue: number;
  orders: number;
}

export interface Cohort {
  cohort: string;
  size: number;
  retention: { offset: number; customers: number; rate: number }[];
}

export interface Order {
  order_id: string;
  order_date: string;
  customer: string;
  country: string;
  status: string;
  items: number;
  revenue: number;
}

export const emptyFilters: Filters = { category: [], country: [], status: [] };

/** Serialise filters as repeated query keys, matching FastAPI list params. */
export function toQuery(filters: Filters, extra: Record<string, string | number> = {}): string {
  const params = new URLSearchParams();
  if (filters.start) params.set("start", filters.start);
  if (filters.end) params.set("end", filters.end);
  for (const key of ["category", "country", "status"] as const) {
    for (const value of filters[key]) params.append(key, value);
  }
  for (const [key, value] of Object.entries(extra)) params.set(key, String(value));
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** Pivot cohorts into a rectangular grid of retention rates by month offset. */
export function cohortGrid(cohorts: Cohort[]): { width: number; rows: (number | null)[][] } {
  const width = Math.max(0, ...cohorts.flatMap((c) => c.retention.map((r) => r.offset + 1)));
  const rows = cohorts.map((c) => {
    const row: (number | null)[] = Array(width).fill(null);
    for (const r of c.retention) row[r.offset] = r.rate;
    return row;
  });
  return { width, rows };
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json() as Promise<T>;
}
