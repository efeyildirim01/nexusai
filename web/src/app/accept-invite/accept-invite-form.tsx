"use client";

import { useState, type FormEvent } from "react";
import { authAction } from "@/lib/api";
import { Alert, Button, Field, Input } from "@/components/ui";

export function AcceptInviteForm() {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    // The token travels in the URL fragment (#token=...), which browsers never send to
    // servers or put in Referer headers.
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (!token) {
      setError("This link is missing its invitation token. Ask for a new invitation.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await authAction("accept-invite", {
        token,
        full_name: form.get("full_name"),
        password: form.get("password"),
      });
      // Full navigation so the new session cookies apply to every request.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/app");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not accept the invitation");
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {error && <Alert>{error}</Alert>}
      <Field label="Your name">
        <Input name="full_name" required autoComplete="name" maxLength={200} />
      </Field>
      <Field label="Password" hint="At least 12 characters.">
        <Input name="password" type="password" required minLength={12} maxLength={128} autoComplete="new-password" />
      </Field>
      <Button type="submit" disabled={pending} className="w-full">
        {pending ? "Joining…" : "Join workspace"}
      </Button>
    </form>
  );
}
