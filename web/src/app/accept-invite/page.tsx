import type { Metadata } from "next";
import { AuthShell } from "@/components/auth-shell";
import { AcceptInviteForm } from "./accept-invite-form";

export const metadata: Metadata = { title: "Join workspace" };

export default function AcceptInvitePage() {
  return (
    <AuthShell title="Join your team" subtitle="Set your name and a password to accept the invitation.">
      <AcceptInviteForm />
    </AuthShell>
  );
}
