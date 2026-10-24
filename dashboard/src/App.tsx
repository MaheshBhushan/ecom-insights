import { useEffect, useState } from "react";
import {
  cohortGrid,
  emptyFilters,
  getJson,
  toQuery,
  type Cohort,
  type Filters,
  type MonthRevenue,
  type Options,
  type Order,
  type Summary,
} from "./api";

const money = new Intl.NumberFormat("en-GB", { style: "currency", currency: "EUR" });
const count = new Intl.NumberFormat("en-GB");

interface Data {
  summary: Summary;
  revenue: MonthRevenue[];
  cohorts: Cohort[];
  orders: Order[];
}

function MultiSelect(props: { label: string; values: string[]; selected: string[]; onChange: (v: string[]) => void }) {
  return (
    <label>
      {props.label}
      <select
        multiple
        value={props.selected}
        onChange={(e) => props.onChange(Array.from(e.target.selectedOptions, (o) => o.value))}
      >
        {props.values.map((v) => (
          <option key={v}>{v}</option>
        ))}
      </select>
    </label>
  );
}

function RevenueChart({ months }: { months: MonthRevenue[] }) {
  const max = Math.max(1, ...months.map((m) => m.revenue));
  return (
    <div className="bars" role="img" aria-label="Net revenue by month">
      {months.map((m) => (
        <div key={m.month} className="bar" title={`${m.month}: ${money.format(m.revenue)}, ${m.orders} orders`}>
          <span style={{ height: `${(m.revenue / max) * 100}%` }} />
          <small>{m.month}</small>
        </div>
      ))}
    </div>
  );
}

function CohortTable({ cohorts }: { cohorts: Cohort[] }) {
  const { width, rows } = cohortGrid(cohorts);
  return (
    <table className="cohorts">
      <thead>
        <tr>
          <th>Cohort</th>
          <th>Size</th>
          {Array.from({ length: width }, (_, i) => (
            <th key={i}>M{i}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {cohorts.map((c, i) => (
          <tr key={c.cohort}>
            <td>{c.cohort}</td>
            <td>{c.size}</td>
            {rows[i].map((rate, j) => (
              <td key={j} style={rate === null ? undefined : { background: `rgba(37, 99, 235, ${rate})`, color: rate > 0.5 ? "#fff" : undefined }}>
                {rate === null ? "" : `${Math.round(rate * 100)}%`}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function App() {
  const [options, setOptions] = useState<Options | null>(null);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJson<Options>("/api/dashboard/options").then(setOptions, (e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const q = toQuery(filters);
    Promise.all([
      getJson<Summary>(`/api/dashboard/summary${q}`, controller.signal),
      getJson<MonthRevenue[]>(`/api/dashboard/revenue${q}`, controller.signal),
      getJson<Cohort[]>(`/api/dashboard/cohorts${q}`, controller.signal),
      getJson<Order[]>(`/api/dashboard/orders${toQuery(filters, { limit: 25 })}`, controller.signal),
    ]).then(
      ([summary, revenue, cohorts, orders]) => {
        setData({ summary, revenue, cohorts, orders });
        setError(null);
      },
      (e: Error) => e.name !== "AbortError" && setError(e.message),
    );
    return () => controller.abort();
  }, [filters]);

  const set = (patch: Partial<Filters>) => setFilters((f) => ({ ...f, ...patch }));

  return (
    <main>
      <h1>ecom-insights KPI dashboard</h1>
      <form className="filters" onSubmit={(e) => e.preventDefault()}>
        <label>
          From
          <input type="date" min={options?.min_date ?? undefined} max={options?.max_date ?? undefined}
            value={filters.start ?? ""} onChange={(e) => set({ start: e.target.value || undefined })} />
        </label>
        <label>
          To
          <input type="date" min={options?.min_date ?? undefined} max={options?.max_date ?? undefined}
            value={filters.end ?? ""} onChange={(e) => set({ end: e.target.value || undefined })} />
        </label>
        <MultiSelect label="Category" values={options?.categories ?? []} selected={filters.category} onChange={(category) => set({ category })} />
        <MultiSelect label="Country" values={options?.countries ?? []} selected={filters.country} onChange={(country) => set({ country })} />
        <MultiSelect label="Status" values={options?.statuses ?? []} selected={filters.status} onChange={(status) => set({ status })} />
        <button type="button" onClick={() => setFilters(emptyFilters)}>Reset</button>
      </form>
      {error && <p className="error">{error}</p>}
      {data && (
        <>
          <section className="kpis">
            <div><small>Net revenue</small><strong>{money.format(data.summary.revenue)}</strong></div>
            <div><small>Orders</small><strong>{count.format(data.summary.orders)}</strong></div>
            <div><small>Customers</small><strong>{count.format(data.summary.customers)}</strong></div>
            <div><small>Avg order value</small><strong>{money.format(data.summary.avg_order_value)}</strong></div>
          </section>
          <section>
            <h2>Revenue by month</h2>
            <RevenueChart months={data.revenue} />
          </section>
          <section>
            <h2>Cohort retention</h2>
            <CohortTable cohorts={data.cohorts} />
          </section>
          <section>
            <h2>Latest orders</h2>
            <table>
              <thead>
                <tr><th>Order</th><th>Date</th><th>Customer</th><th>Country</th><th>Status</th><th>Items</th><th>Revenue</th></tr>
              </thead>
              <tbody>
                {data.orders.map((o) => (
                  <tr key={o.order_id}>
                    <td>{o.order_id}</td><td>{o.order_date}</td><td>{o.customer}</td><td>{o.country}</td>
                    <td>{o.status}</td><td>{o.items}</td><td>{money.format(o.revenue)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </main>
  );
}
