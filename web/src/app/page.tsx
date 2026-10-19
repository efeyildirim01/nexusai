import Link from "next/link";

const features = [
  {
    title: "Upload and validate",
    body: "CSV and Excel files are mapped to a sales model, checked row by row, and every rejected line comes back with its row, column and reason.",
  },
  {
    title: "Dashboards that compare",
    body: "Revenue, orders, customers, margin and returns against the previous period, with breakdowns and filters by region, category and channel.",
  },
  {
    title: "Ask in plain English",
    body: "Questions become SQL that is validated, run read-only, time-limited and confined to your company's data. The AI never gets raw database access.",
  },
  {
    title: "Isolation in the database",
    body: "Every company's rows are separated by PostgreSQL Row-Level Security, not just application code. Four roles control who can see and change what.",
  },
  {
    title: "Anomalies explained",
    body: "Unusual days and weeks are detected statistically and summarised in words, from aggregate figures only.",
  },
  {
    title: "Reports to share",
    body: "Export the current view as a PDF report or an Excel workbook with every underlying sales line.",
  },
];

export default function Home() {
  return (
    <main className="flex-1">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
        <span className="text-lg font-semibold tracking-tight text-slate-900">
          Nexus<span className="text-indigo-600">AI</span>
        </span>
        <nav className="flex items-center gap-2 text-sm">
          <Link href="/sign-in" className="rounded-lg px-3 py-2 text-slate-700 hover:bg-slate-100">
            Sign in
          </Link>
          <Link
            href="/sign-up"
            className="rounded-lg bg-indigo-600 px-3 py-2 font-medium text-white hover:bg-indigo-500"
          >
            Create workspace
          </Link>
        </nav>
      </header>

      <section className="mx-auto max-w-6xl px-4 pb-16 pt-12 sm:px-6 sm:pt-20">
        <p className="text-sm font-medium text-indigo-600">Business intelligence for growing companies</p>
        <h1 className="mt-3 max-w-3xl text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
          Upload your sales data. Ask questions. Get answers you can trust.
        </h1>
        <p className="mt-5 max-w-2xl text-lg text-slate-600">
          NexusAI turns spreadsheets into dashboards and lets your team ask &ldquo;Which products
          generated the highest revenue last quarter?&rdquo; without writing SQL, and without
          handing an AI the keys to your database.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link
            href="/sign-up"
            className="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-500"
          >
            Start free
          </Link>
          <Link
            href="/sign-in"
            className="rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 hover:bg-slate-50"
          >
            I have an account
          </Link>
        </div>
      </section>

      <section className="border-t border-slate-200 bg-white">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-16 sm:grid-cols-2 sm:px-6 lg:grid-cols-3">
          {features.map((f) => (
            <div key={f.title}>
              <h2 className="font-semibold text-slate-900">{f.title}</h2>
              <p className="mt-2 text-sm leading-6 text-slate-600">{f.body}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
