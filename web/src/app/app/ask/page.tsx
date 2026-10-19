"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { RankChart, TrendChart } from "@/components/charts";
import { Alert, Badge, Button, Card, Empty, PageHeader, cx, dateTime } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { AiStatus, HistoryItem, QueryResult } from "@/lib/types";

const EXAMPLES = [
  "Which products generated the highest revenue last quarter?",
  "Monthly revenue trend for the last 12 months",
  "Which region has the highest return rate?",
  "Top 10 customers by revenue this year",
];

function ResultView({ result }: { result: QueryResult }) {
  const rows = result.rows.map((row) => Object.fromEntries(result.columns.map((c, i) => [c, row[i]])));
  const { chart } = result;
  return (
    <Card
      title={result.question ?? "Query result"}
      action={<span className="text-xs text-slate-500">{result.row_count} rows · {result.elapsed_ms} ms{result.truncated && " · truncated"}</span>}
    >
      {result.explanation && <p className="mb-4 text-sm text-slate-600">{result.explanation}</p>}
      {chart.type !== "table" && chart.x && chart.y && rows.length > 1 && (
        <div className="mb-4">
          {chart.type === "line" ? (
            <TrendChart data={rows} x={chart.x} y={chart.y} />
          ) : (
            <RankChart data={rows.slice(0, 15)} x={chart.x} y={chart.y} height={Math.max(160, Math.min(rows.length, 15) * 30)} />
          )}
        </div>
      )}
      {rows.length === 0 ? (
        <Empty>The query returned no rows.</Empty>
      ) : (
        <div className="max-h-96 overflow-auto rounded-lg border border-slate-200">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs text-slate-500">
              <tr>{result.columns.map((c) => <th key={c} className="px-3 py-2 font-medium">{c}</th>)}</tr>
            </thead>
            <tbody>
              {result.rows.map((row, i) => (
                <tr key={i} className="border-t border-slate-100">
                  {row.map((value, j) => (
                    <td key={j} className={cx("px-3 py-1.5", typeof value === "number" && "text-right tabular-nums")}>
                      {typeof value === "number" ? value.toLocaleString("en-GB", { maximumFractionDigits: 2 }) : String(value ?? "—")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <details className="mt-4">
        <summary className="cursor-pointer text-xs font-medium text-slate-500">SQL that ran (validated, read-only)</summary>
        <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">{result.sql}</pre>
      </details>
    </Card>
  );
}

export default function AskPage() {
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [mode, setMode] = useState<"question" | "sql">("question");
  const [text, setText] = useState("");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<{ message: string; sql?: string } | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [pending, setPending] = useState(false);

  const loadHistory = useCallback(() => api<HistoryItem[]>("ai/history").then(setHistory).catch(() => undefined), []);
  useEffect(() => {
    api<AiStatus>("ai/status").then((s) => {
      setStatus(s);
      if (!s.natural_language) setMode("sql");
    });
    loadHistory();
  }, [loadHistory]);

  async function run(event?: FormEvent) {
    event?.preventDefault();
    if (!text.trim()) return;
    setPending(true);
    setError(null);
    setResult(null);
    try {
      const body = mode === "question" ? { question: text } : { sql: text };
      setResult(await api<QueryResult>(mode === "question" ? "ai/query" : "ai/sql", { method: "POST", json: body }));
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : null;
      const sql = detail && typeof detail === "object" && "sql" in detail ? String((detail as { sql: unknown }).sql) : undefined;
      setError({ message: e instanceof Error ? e.message : "Query failed", sql });
    } finally {
      setPending(false);
      loadHistory();
    }
  }

  return (
    <>
      <PageHeader
        title="Ask AI"
        description="Questions are turned into SQL, then validated and run read-only against your company's data only."
      />
      {status && !status.natural_language && (
        <div className="mb-4">
          <Alert tone="info">Natural-language questions are switched off on this server (no AI key configured). The SQL console uses the same safety layer.</Alert>
        </div>
      )}
      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <Card>
            <div className="mb-3 flex gap-1 rounded-lg bg-slate-100 p-1 text-sm">
              {(["question", "sql"] as const).map((m) => (
                <button
                  key={m}
                  disabled={m === "question" && !status?.natural_language}
                  onClick={() => setMode(m)}
                  className={cx("flex-1 rounded-md px-3 py-1.5 font-medium disabled:opacity-40", mode === m ? "bg-white text-slate-900 shadow-sm" : "text-slate-600")}
                >
                  {m === "question" ? "Plain English" : "SQL console"}
                </button>
              ))}
            </div>
            <form onSubmit={run} className="space-y-3">
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && run()}
                rows={mode === "sql" ? 6 : 3}
                maxLength={mode === "sql" ? 5000 : 500}
                placeholder={mode === "question" ? "Which products generated the highest revenue last quarter?" : "SELECT region, SUM(revenue) AS revenue FROM sales WHERE status = 'completed' GROUP BY region ORDER BY revenue DESC"}
                className={cx("w-full rounded-lg border border-slate-300 p-3 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20", mode === "sql" && "font-mono")}
              />
              <div className="flex flex-wrap items-center justify-between gap-3">
                {mode === "question" ? (
                  <div className="flex flex-wrap gap-1.5">
                    {EXAMPLES.map((q) => (
                      <button key={q} type="button" onClick={() => setText(q)} className="rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50">
                        {q}
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-slate-500">One SELECT over the <code>sales</code> view. Max {status?.max_rows} rows, {status?.timeout_ms} ms.</p>
                )}
                <Button type="submit" disabled={pending || !text.trim()}>{pending ? "Running…" : "Run"}</Button>
              </div>
            </form>
          </Card>
          {error && (
            <Alert>
              {error.message}
              {error.sql && <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded bg-red-100/60 p-2 font-mono text-xs">{error.sql}</pre>}
            </Alert>
          )}
          {result && <ResultView result={result} />}
        </div>

        <Card title="Recent queries">
          {history.length === 0 ? (
            <Empty>Nothing yet.</Empty>
          ) : (
            <ul className="space-y-3">
              {history.slice(0, 15).map((h) => (
                <li key={h.id}>
                  <button
                    className="w-full text-left"
                    onClick={() => {
                      const isQuestion = h.source === "natural_language" && status?.natural_language;
                      setMode(isQuestion ? "question" : "sql");
                      setText((isQuestion ? h.question : h.sql) ?? "");
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <Badge tone={h.status === "OK" ? "green" : h.status === "BLOCKED" ? "red" : "amber"}>{h.status.toLowerCase()}</Badge>
                      <span className="text-xs text-slate-400">{dateTime(h.created_at)}</span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm text-slate-700">{h.question ?? h.sql}</p>
                    {h.error && <p className="mt-0.5 line-clamp-1 text-xs text-red-600">{h.error}</p>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
