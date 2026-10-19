"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useMe } from "@/components/app-shell";
import { Alert, Badge, Button, Card, Empty, Field, Input, PageHeader, Select, dateTime } from "@/components/ui";
import { api } from "@/lib/api";
import { ROLE_RANK, atLeast, type AuditEntry, type Invitation, type Role, type User } from "@/lib/types";

const ROLES: Role[] = ["ADMIN", "ANALYST", "VIEWER"];

export default function TeamPage() {
  const me = useMe();
  const isAdmin = atLeast(me.user.role, "ADMIN");
  const assignable = ROLES.filter((r) => ROLE_RANK[r] < ROLE_RANK[me.user.role]);
  const [users, setUsers] = useState<User[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<User[]>("users").then(setUsers).catch(() => undefined);
    if (isAdmin) {
      api<Invitation[]>("invitations").then(setInvitations).catch(() => undefined);
      api<AuditEntry[]>("audit-logs?limit=50").then(setAudit).catch(() => undefined);
    }
  }, [isAdmin]);
  useEffect(() => {
    load();
  }, [load]);

  const names = Object.fromEntries(users.map((u) => [u.id, u.full_name]));

  async function act(promise: Promise<unknown>) {
    setError(null);
    try {
      await promise;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
    load();
  }

  async function invite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setError(null);
    try {
      const created = await api<Invitation>("invitations", {
        method: "POST",
        json: { email: form.get("email"), role: form.get("role") },
      });
      setInviteLink(`${window.location.origin}/accept-invite#token=${created.token}`);
      formElement.reset();
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Invitation failed");
    }
  }

  const manageable = (u: User) => u.id !== me.user.id && ROLE_RANK[me.user.role] > ROLE_RANK[u.role];

  return (
    <>
      <PageHeader title="Team & audit" description={`Members of ${me.tenant.name} (workspace “${me.tenant.slug}”).`} />
      {error && <div className="mb-4"><Alert>{error}</Alert></div>}
      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <Card title="Members">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs uppercase text-slate-500">
                  <tr><th className="py-2">Name</th><th className="py-2">Role</th><th className="py-2">Status</th>{isAdmin && <th />}</tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id} className="border-t border-slate-100">
                      <td className="py-2.5">
                        <p className="font-medium text-slate-900">{u.full_name}{u.id === me.user.id && <span className="text-slate-400"> (you)</span>}</p>
                        <p className="text-xs text-slate-500">{u.email}</p>
                      </td>
                      <td className="py-2.5">
                        {isAdmin && manageable(u) && u.is_active ? (
                          <Select
                            value={u.role}
                            onChange={(e) => act(api(`users/${u.id}/role`, { method: "PATCH", json: { role: e.target.value } }))}
                          >
                            {[u.role, ...assignable.filter((r) => r !== u.role)].map((r) => <option key={r}>{r}</option>)}
                          </Select>
                        ) : (
                          <Badge tone="indigo">{u.role}</Badge>
                        )}
                      </td>
                      <td className="py-2.5">{u.is_active ? <Badge tone="green">active</Badge> : <Badge>deactivated</Badge>}</td>
                      {isAdmin && (
                        <td className="py-2.5 text-right">
                          {manageable(u) && u.is_active && (
                            <Button
                              variant="danger"
                              onClick={() => window.confirm(`Deactivate ${u.full_name}? They are signed out everywhere.`) && act(api(`users/${u.id}/deactivate`, { method: "POST" }))}
                            >
                              Deactivate
                            </Button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {isAdmin && (
            <Card title="Audit log" action={<span className="text-xs text-slate-500">latest 50</span>}>
              {audit.length === 0 ? (
                <Empty>No events.</Empty>
              ) : (
                <ul className="divide-y divide-slate-100 text-sm">
                  {audit.map((a) => (
                    <li key={a.id} className="flex flex-wrap items-baseline justify-between gap-2 py-2">
                      <div>
                        <span className="font-mono text-xs text-slate-800">{a.action}</span>
                        <span className="ml-2 text-slate-500">{a.actor_user_id ? names[a.actor_user_id] ?? "unknown user" : "system"}</span>
                        {Object.keys(a.details).length > 0 && (
                          <span className="ml-2 text-xs text-slate-400">
                            {Object.entries(a.details).filter(([, v]) => v !== null && typeof v !== "object").map(([k, v]) => `${k}=${String(v)}`).join(" ")}
                          </span>
                        )}
                      </div>
                      <span className="text-xs text-slate-400">{dateTime(a.created_at)}{a.ip_address && ` · ${a.ip_address}`}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
        </div>

        {isAdmin ? (
          <div className="space-y-6">
            <Card title="Invite someone">
              <form onSubmit={invite} className="space-y-3">
                <Field label="Email"><Input name="email" type="email" required /></Field>
                <Field label="Role" hint="You can grant roles below your own.">
                  <Select name="role" className="w-full" defaultValue="VIEWER">
                    {assignable.map((r) => <option key={r}>{r}</option>)}
                  </Select>
                </Field>
                <Button type="submit" className="w-full">Create invitation</Button>
              </form>
              {inviteLink && (
                <div className="mt-4 space-y-2">
                  <Alert tone="success">Invitation created. Send this link to them; it works once and expires in 7 days.</Alert>
                  <div className="flex gap-2">
                    <Input readOnly value={inviteLink} onFocus={(e) => e.currentTarget.select()} className="font-mono text-xs" />
                    <Button variant="secondary" onClick={() => navigator.clipboard.writeText(inviteLink)}>Copy</Button>
                  </div>
                </div>
              )}
            </Card>
            <Card title="Pending invitations">
              {invitations.filter((i) => !i.accepted_at && !i.revoked_at).length === 0 ? (
                <Empty>None.</Empty>
              ) : (
                <ul className="space-y-2 text-sm">
                  {invitations.filter((i) => !i.accepted_at && !i.revoked_at).map((i) => (
                    <li key={i.id} className="flex items-center justify-between gap-2">
                      <div>
                        <p className="text-slate-800">{i.email}</p>
                        <p className="text-xs text-slate-500">{i.role} · expires {dateTime(i.expires_at)}</p>
                      </div>
                      <Button variant="ghost" onClick={() => act(api(`invitations/${i.id}`, { method: "DELETE" }))}>Revoke</Button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        ) : (
          <Alert tone="info">Only owners and admins can invite people or see the audit log.</Alert>
        )}
      </div>
    </>
  );
}
