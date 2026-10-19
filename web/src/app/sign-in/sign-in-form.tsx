"use client";

import { useState, type FormEvent } from "react";
import { authAction } from "@/lib/api";
import { Alert, Button, Field, Input } from "@/components/ui";

function nextPath(): string {
  const next = new URLSearchParams(window.location.search).get("next");
  // Only same-site relative paths: never redirect to another origin.
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/app";
}

export function SignInForm() {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      await authAction("signin", {
        workspace: form.get("workspace"),
        email: form.get("email"),
        password: form.get("password"),
      });
      // Full navigation so the new session cookies apply to every request.
      window.location.assign(nextPath());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign-in failed");
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {error && <Alert>{error}</Alert>}
      <Field label="Workspace">
        <Input name="workspace" required autoComplete="organization" placeholder="acme" />
      </Field>
      <Field label="Email">
        <Input name="email" type="email" required autoComplete="email" />
      </Field>
      <Field label="Password">
        <Input name="password" type="password" required autoComplete="current-password" />
      </Field>
      <Button type="submit" disabled={pending} className="w-full">
        {pending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
