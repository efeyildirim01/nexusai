"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useMe } from "@/components/app-shell";
import { Alert, Badge, Button, Card, Empty, Field, Input, PageHeader, dateTime } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { atLeast, type Dataset, type DatasetDetail } from "@/lib/types";

function IssueList({ detail }: { detail: DatasetDetail }) {
  if (!detail.issues.length) return <p className="text-sm text-emerald-700">Every row passed validation.</p>;
  return (
    <div className="max-h-80 overflow-auto rounded-lg border border-slate-200">
      <table className="w-full text-left text-sm">
        <thead className="sticky top-0 bg-slate-50 text-xs uppercase text-slate-500">
          <tr><th className="px-3 py-2">Row</th><th className="px-3 py-2">Column</th><th className="px-3 py-2">Problem</th></tr>
        </thead>
        <tbody>
          {detail.issues.map((issue, i) => (
            <tr key={i} className="border-t border-slate-100">
              <td className="px-3 py-1.5 tabular-nums text-slate-600">{issue.row_number ?? "—"}</td>
              <td className="px-3 py-1.5 font-mono text-xs text-slate-700">{issue.column_name ?? "—"}</td>
              <td className="px-3 py-1.5">
                <Badge tone={issue.severity === "ERROR" ? "red" : "amber"}>{issue.severity.toLowerCase()}</Badge>{" "}
                <span className="text-slate-700">{issue.message}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DataPage() {
  const me = useMe();
  const canUpload = atLeast(me.user.role, "ANALYST");
  const canDelete = atLeast(me.user.role, "ADMIN");
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [result, setResult] = useState<DatasetDetail | null>(null);
  const [selected, setSelected] = useState<DatasetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const load = useCallback(() => api<Dataset[]>("datasets").then(setDatasets).catch(() => undefined), []);
  useEffect(() => {
    load();
  }, [load]);

  async function onUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    if (!form.get("name")) form.delete("name");
    setPending(true);
    setError(null);
    setResult(null);
    try {
      const detail = await api<DatasetDetail>("datasets", { method: "POST", body: form });
      setResult(detail);
      formElement.reset();
      load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed");
    } finally {
      setPending(false);
    }
  }

  async function remove(id: string) {
    if (!window.confirm("Delete this dataset and all its sales rows?")) return;
    await api(`datasets/${id}`, { method: "DELETE" }).catch((e: Error) => setError(e.message));
    if (selected?.id === id) setSelected(null);
    load();
  }

  return (
    <>
      <PageHeader
        title="Data"
        description="Upload sales lines as CSV or Excel. Each row is validated; problems are listed with row and column."
        action={
          <a href="/api/backend/datasets/template" download>
            <Button variant="secondary">Download template</Button>
          </a>
        }
      />
      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-6 lg:col-span-2">
          {canUpload ? (
            <Card title="Upload a file">
              <form onSubmit={onUpload} className="space-y-4">
                {error && <Alert>{error}</Alert>}
                <Field label="File" hint="CSV or .xlsx, up to 20 MB / 200,000 rows. Needs at least a date, a product and revenue or unit price.">
                  <Input name="file" type="file" accept=".csv,.xlsx" required />
                </Field>
                <Field label="Name (optional)">
                  <Input name="name" maxLength={200} placeholder="Q3 Shopify export" />
                </Field>
                <Button type="submit" disabled={pending} className="w-full">{pending ? "Validating…" : "Upload and validate"}</Button>
              </form>
            </Card>
          ) : (
            <Alert tone="info">Viewers can see datasets; analysts and above can upload.</Alert>
          )}

          {result && (
            <Card title="Validation result">
              <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
                <Badge tone={result.status === "READY" ? "green" : "red"}>{result.status === "READY" ? "imported" : "rejected"}</Badge>
                <span className="text-slate-700">
                  {result.imported_rows.toLocaleString("en-GB")} of {result.total_rows.toLocaleString("en-GB")} rows imported
                  {result.rejected_rows > 0 && `, ${result.rejected_rows.toLocaleString("en-GB")} rejected`}
                </span>
              </div>
              {result.status === "REJECTED" && (
                <div className="mb-3"><Alert tone="warning">More than 20% of rows were invalid, so nothing was imported. Fix the file and upload it again.</Alert></div>
              )}
              <IssueList detail={result} />
            </Card>
          )}
        </div>

        <div className="space-y-6 lg:col-span-3">
          <Card title="Datasets">
            {datasets.length === 0 ? (
              <Empty>No uploads yet.</Empty>
            ) : (
              <ul className="divide-y divide-slate-100">
                {datasets.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium text-slate-900">{d.name}</p>
                      <p className="text-xs text-slate-500">
                        {dateTime(d.created_at)} · {d.imported_rows.toLocaleString("en-GB")} rows
                        {d.rejected_rows > 0 && ` · ${d.rejected_rows} rejected`}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge tone={d.status === "READY" ? "green" : "red"}>{d.status.toLowerCase()}</Badge>
                      <Button variant="ghost" onClick={() => api<DatasetDetail>(`datasets/${d.id}`).then(setSelected)}>Details</Button>
                      {canDelete && <Button variant="danger" onClick={() => remove(d.id)}>Delete</Button>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {selected && (
            <Card title={selected.name} action={<Button variant="ghost" onClick={() => setSelected(null)}>Close</Button>}>
              <p className="mb-2 text-xs font-medium uppercase text-slate-500">Column mapping</p>
              <div className="mb-4 flex flex-wrap gap-1.5">
                {Object.entries(selected.column_mapping).map(([target, source]) => (
                  <span key={target} className="rounded-md bg-slate-100 px-2 py-1 font-mono text-xs text-slate-700">
                    {source} → {target}
                  </span>
                ))}
              </div>
              <IssueList detail={selected} />
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
