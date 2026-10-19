"use client";

import { useState, type FormEvent } from "react";
import { authAction } from "@/lib/api";
import { Alert, Button, Field, Input } from "@/components/ui";

function toSlug(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

export function SignUpForm() {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [workspace, setWorkspace] = useState("");
  const [touched, setTouched] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      await authAction("signup", {
        company_name: form.get("company_name"),
        workspace,
        full_name: form.get("full_name"),
        email: form.get("email"),
        password: form.get("password"),
      });
      // Full navigation so the new session cookies apply to every request.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/app/data");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign-up failed");
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {error && <Alert>{error}</Alert>}
      <Field label="Company name">
        <Input
          name="company_name"
          required
          maxLength={200}
          onChange={(e) => !touched && setWorkspace(toSlug(e.target.value))}
        />
      </Field>
      <Field label="Workspace" hint="Lowercase letters, numbers and dashes. Your team signs in with it.">
        <Input
          value={workspace}
          required
          pattern="[a-z0-9][a-z0-9\-]{1,38}[a-z0-9]"
          onChange={(e) => {
            setTouched(true);
            setWorkspace(e.target.value.toLowerCase());
          }}
        />
      </Field>
      <Field label="Your name">
        <Input name="full_name" required autoComplete="name" maxLength={200} />
      </Field>
      <Field label="Work email">
        <Input name="email" type="email" required autoComplete="email" />
      </Field>
      <Field label="Password" hint="At least 12 characters.">
        <Input name="password" type="password" required minLength={12} maxLength={128} autoComplete="new-password" />
      </Field>
      <Button type="submit" disabled={pending} className="w-full">
        {pending ? "Creating…" : "Create workspace"}
      </Button>
    </form>
  );
}
