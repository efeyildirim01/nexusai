export type Role = "OWNER" | "ADMIN" | "ANALYST" | "VIEWER";

export const ROLE_RANK: Record<Role, number> = { VIEWER: 1, ANALYST: 2, ADMIN: 3, OWNER: 4 };

export function atLeast(role: Role, minimum: Role): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[minimum];
}

export type User = {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
};

export type Me = {
  user: User;
  tenant: { id: string; name: string; slug: string; created_at: string };
};

export type Breakdown = { key: string; revenue: number; lines: number };

export type Anomaly = {
  period: string;
  revenue: number;
  expected: number;
  score: number;
  direction: "spike" | "drop";
};

export type Overview = {
  period: { date_from: string | null; date_to: string | null; grain: "day" | "week" | "month" };
  kpis: {
    revenue: number;
    orders: number;
    customers: number;
    units: number;
    average_order_value: number;
    gross_margin_pct: number;
    return_rate_pct: number;
    lines: number;
  };
  deltas_pct: Record<"revenue" | "orders" | "customers" | "average_order_value", number | null>;
  timeseries: { period: string; revenue: number; orders: number }[];
  by_category: Breakdown[];
  by_region: Breakdown[];
  by_channel: Breakdown[];
  top_products: Breakdown[];
  top_customers: Breakdown[];
  status: Breakdown[];
  customer_mix: { new: number; returning: number };
  anomalies: Anomaly[];
};

export type FilterOptions = {
  regions: string[];
  categories: string[];
  channels: string[];
  date_min: string | null;
  date_max: string | null;
};

export type Summary = {
  headline: string;
  summary: string;
  anomalies: Anomaly[];
  anomaly_explanations: string[];
  source: "llm" | "template";
};

export type Issue = {
  row_number: number | null;
  column_name: string | null;
  severity: "ERROR" | "WARNING";
  message: string;
};

export type Dataset = {
  id: string;
  name: string;
  filename: string;
  file_format: string;
  status: "READY" | "REJECTED";
  total_rows: number;
  imported_rows: number;
  rejected_rows: number;
  column_mapping: Record<string, string>;
  uploaded_by_id: string;
  created_at: string;
};

export type DatasetDetail = Dataset & {
  issues: Issue[];
  error_count: number;
  warning_count: number;
};

export type QueryResult = {
  id: string;
  question: string | null;
  sql: string;
  explanation: string | null;
  columns: string[];
  rows: (string | number | boolean | null)[][];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
  chart: { type: "line" | "bar" | "table"; x: string | null; y: string | null };
};

export type HistoryItem = {
  id: string;
  source: "natural_language" | "sql";
  question: string | null;
  sql: string | null;
  status: "OK" | "BLOCKED" | "FAILED" | "UNANSWERABLE";
  error: string | null;
  row_count: number | null;
  elapsed_ms: number | null;
  created_at: string;
};

export type AiStatus = {
  natural_language: boolean;
  sql_console: boolean;
  model: string | null;
  max_rows: number;
  timeout_ms: number;
  queries_per_minute: number;
};

export type Invitation = {
  id: string;
  email: string;
  role: Role;
  expires_at: string;
  created_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  token?: string;
};

export type AuditEntry = {
  id: number;
  actor_user_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  details: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
};
