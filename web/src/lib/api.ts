"use client";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(ApiError.describe(detail));
  }

  static describe(detail: unknown): string {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d: { loc?: unknown[]; msg?: string }) => {
          const field = d.loc?.[d.loc.length - 1];
          return field ? `${String(field)}: ${d.msg}` : d.msg;
        })
        .join("; ");
    }
    if (detail && typeof detail === "object" && "error" in detail) {
      return String((detail as { error: unknown }).error);
    }
    return "Something went wrong";
  }
}

const CSRF = { "x-nexus-csrf": "1" };

async function parse<T>(response: Response): Promise<T> {
  if (response.status === 401 && typeof window !== "undefined") {
    // Outside React (no router here); a full navigation also discards stale state.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = `/sign-in?next=${encodeURIComponent(window.location.pathname)}`;
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, (body as { detail?: unknown }).detail);
  return body as T;
}

/** Calls the FastAPI service through the Next.js BFF (`/api/backend/...`). */
export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const response = await fetch(`/api/backend/${path.replace(/^\//, "")}`, {
    ...rest,
    headers: {
      ...CSRF,
      ...(json !== undefined ? { "content-type": "application/json" } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  return parse<T>(response);
}

export async function authAction(action: string, payload: unknown): Promise<void> {
  const response = await fetch(`/api/auth/${action}`, {
    method: "POST",
    headers: { ...CSRF, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, (body as { detail?: unknown }).detail);
  }
}

export function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) search.set(key, value);
  const text = search.toString();
  return text ? `?${text}` : "";
}
