"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { RankChart, TrendChart } from "@/components/charts";
import { Alert, Badge, Button, Card, Empty, Input, PageHeader, Select, compact, cx, money } from "@/components/ui";
import { api, query } from "@/lib/api";
import type { Breakdown, FilterOptions, Overview, Summary } from "@/lib/types";

type Filters = { date_from?: string; date_to?: string; region?: string; category?: string; channel?: string };

function Delta({ value }: { value: number | null }) {
  if (value === null) return <span className="text-xs text-slate-400">no prior period</span>;
  const up = value >= 0;
  return (
    <span className={cx("text-xs font-medium", up ? "text-emerald-600" : "text-red-600")}>
      {up ? "▲" : "▼"} {Math.abs(value).toFixed(1)}%
    </span>
  );
}

function Kpi({ label, value, delta }: { label: string; value: string; delta?: number | null }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{value}</p>
      {delta !== undefined && <div className="mt-1"><Delta value={delta} /></div>}
    </div>
  );
}

function BreakdownTable({ rows, total }: { rows: Breakdown[]; total: number }) {
  if (!rows.length) return <Empty>No data</Empty>;
  return (
    <table className="w-full text-sm">
      <tbody>
        {rows.map((r) => (
          <tr key={r.key} className="border-t border-slate-100 first:border-0">
            <td className="py-2 pr-2 text-slate-700">{r.key}</td>
            <td className="py-2 text-right tabular-nums text-slate-900">{money(r.revenue)}</td>
            <td className="w-16 py-2 text-right text-xs tabular-nums text-slate-500">
              {total ? `${((r.revenue / total) * 100).toFixed(0)}%` : ""}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function DashboardPage() {
  const [filters, setFilters] = useState<Filters>({});
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [result, setResult] = useState<{ key: string; data?: Overview; error?: string } | null>(null);
  const [summaryState, setSummaryState] = useState<{ key: string; summary: Summary } | null>(null);
  const key = JSON.stringify(filters);

  useEffect(() => {
    api<FilterOptions>("analytics/filters").then(setOptions).catch(() => undefined);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api<Overview>(`analytics/overview${query(filters)}`)
      .then((d) => {
        if (cancelled) return;
        setResult({ key, data: d });
        if (d.kpis.lines) {
          api<Summary>("ai/summary", { method: "POST", json: filters })
            .then((s) => !cancelled && setSummaryState({ key, summary: s }))
            .catch(() => undefined);
        }
      })
      .catch((e: Error) => !cancelled && setResult({ key, error: e.message }));
    return () => {
      cancelled = true;
    };
  }, [filters, key]);

  // Derived instead of stored: the previous view stays visible (dimmed) while the next loads.
  const loading = result?.key !== key;
  const data = result?.data ?? null;
  const error = result?.error ?? null;
  const summary = summaryState?.key === key ? summaryState.summary : null;

  const exportUrl = useMemo(() => (fmt: string) => `/api/backend/reports/sales.${fmt}${query(filters)}`, [filters]);
  const set = (key: keyof Filters) => (value: string) => setFilters((f) => ({ ...f, [key]: value || undefined }));

  if (!loading && data && !data.kpis.lines && !Object.values(filters).some(Boolean)) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <Card>
          <div className="py-10 text-center">
            <p className="text-slate-700">No sales data yet.</p>
            <p className="mt-1 text-sm text-slate-500">Upload a CSV or Excel export to see your dashboard.</p>
            <Link href="/app/data" className="mt-4 inline-block rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500">
              Upload data
            </Link>
          </div>
        </Card>
      </>
    );
  }

  const k = data?.kpis;
  return (
    <>
      <PageHeader
        title="Dashboard"
        description={data?.period.date_from ? `${data.period.date_from} → ${data.period.date_to}` : undefined}
        action={
          <div className="flex gap-2">
            <a href={exportUrl("pdf")} download><Button variant="secondary">PDF report</Button></a>
            <a href={exportUrl("xlsx")} download><Button variant="secondary">Excel</Button></a>
          </div>
        }
      />

      <div className="mb-6 flex flex-wrap items-end gap-3">
        <label className="text-xs text-slate-500">
          From
          <Input type="date" className="mt-1 w-40" min={options?.date_min ?? undefined} max={options?.date_max ?? undefined} value={filters.date_from ?? ""} onChange={(e) => set("date_from")(e.target.value)} />
        </label>
        <label className="text-xs text-slate-500">
          To
          <Input type="date" className="mt-1 w-40" min={options?.date_min ?? undefined} max={options?.date_max ?? undefined} value={filters.date_to ?? ""} onChange={(e) => set("date_to")(e.target.value)} />
        </label>
        {(["region", "category", "channel"] as const).map((key) => {
          const values = options?.[key === "region" ? "regions" : key === "category" ? "categories" : "channels"] ?? [];
          return (
            <label key={key} className="text-xs capitalize text-slate-500">
              {key}
              <Select className="mt-1 block w-40" value={filters[key] ?? ""} onChange={(e) => set(key)(e.target.value)}>
                <option value="">All</option>
                {values.map((v) => <option key={v}>{v}</option>)}
              </Select>
            </label>
          );
        })}
        {Object.values(filters).some(Boolean) && (
          <Button variant="ghost" onClick={() => setFilters({})}>Clear</Button>
        )}
      </div>

      {error && <Alert>{error}</Alert>}

      <div className={cx("space-y-6 transition-opacity", loading && "opacity-60")}>
        {summary && (
          <Card title={<span className="flex items-center gap-2">Summary <Badge tone={summary.source === "llm" ? "indigo" : "slate"}>{summary.source === "llm" ? "AI" : "Automatic"}</Badge></span>}>
            <p className="font-medium text-slate-900">{summary.headline}</p>
            <p className="mt-2 text-sm leading-6 text-slate-600">{summary.summary}</p>
          </Card>
        )}

        {k && data && (
          <>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
              <Kpi label="Revenue" value={money(k.revenue)} delta={data.deltas_pct.revenue} />
              <Kpi label="Orders" value={k.orders.toLocaleString("en-GB")} delta={data.deltas_pct.orders} />
              <Kpi label="Customers" value={k.customers.toLocaleString("en-GB")} delta={data.deltas_pct.customers} />
              <Kpi label="Avg order" value={money(k.average_order_value)} delta={data.deltas_pct.average_order_value} />
              <Kpi label="Gross margin" value={`${k.gross_margin_pct.toFixed(1)}%`} />
              <Kpi label="Return rate" value={`${k.return_rate_pct.toFixed(1)}%`} />
            </div>

            <Card title={`Revenue by ${data.period.grain}`}>
              {data.timeseries.length ? <TrendChart data={data.timeseries} x="period" y="revenue" /> : <Empty>No data in this period</Empty>}
            </Card>

            {data.anomalies.length > 0 && (
              <Card title="Anomalies">
                <ul className="space-y-3">
                  {data.anomalies.map((a, i) => (
                    <li key={a.period} className="flex gap-3 text-sm">
                      <Badge tone={a.direction === "spike" ? "amber" : "red"}>{a.direction}</Badge>
                      <div>
                        <p className="font-medium text-slate-900">
                          {a.period}: {money(a.revenue)} <span className="font-normal text-slate-500">vs ~{money(a.expected)} expected</span>
                        </p>
                        {summary?.anomaly_explanations[i] && <p className="mt-0.5 text-slate-600">{summary.anomaly_explanations[i]}</p>}
                      </div>
                    </li>
                  ))}
                </ul>
              </Card>
            )}

            <div className="grid gap-6 lg:grid-cols-2">
              <Card title="Revenue by category">
                <RankChart data={data.by_category} x="key" y="revenue" height={Math.max(160, data.by_category.length * 34)} />
              </Card>
              <Card title="Revenue by region">
                <RankChart data={data.by_region} x="key" y="revenue" height={Math.max(160, data.by_region.length * 34)} />
              </Card>
              <Card title="Top products"><BreakdownTable rows={data.top_products} total={k.revenue} /></Card>
              <Card title="Top customers"><BreakdownTable rows={data.top_customers} total={k.revenue} /></Card>
              <Card title="Sales channels"><BreakdownTable rows={data.by_channel} total={k.revenue} /></Card>
              <Card title="Customers">
                <div className="grid grid-cols-2 gap-4 text-center">
                  <div>
                    <p className="text-2xl font-semibold tabular-nums">{compact(data.customer_mix.new)}</p>
                    <p className="text-xs text-slate-500">first-time buyers</p>
                  </div>
                  <div>
                    <p className="text-2xl font-semibold tabular-nums">{compact(data.customer_mix.returning)}</p>
                    <p className="text-xs text-slate-500">returning customers</p>
                  </div>
                </div>
                <div className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500">
                  {data.status.map((s) => `${s.key}: ${s.lines.toLocaleString("en-GB")} lines`).join(" · ")}
                </div>
              </Card>
            </div>
          </>
        )}
      </div>
    </>
  );
}
