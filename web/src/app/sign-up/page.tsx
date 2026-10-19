import type { Metadata } from "next";
import Link from "next/link";
import { AuthShell } from "@/components/auth-shell";
import { SignUpForm } from "./sign-up-form";

export const metadata: Metadata = { title: "Create workspace" };

export default function SignUpPage() {
  return (
    <AuthShell
      title="Create your workspace"
      subtitle="You'll be the owner and can invite your team afterwards."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/sign-in" className="font-medium text-indigo-600 hover:text-indigo-500">
            Sign in
          </Link>
        </>
      }
    >
      <SignUpForm />
    </AuthShell>
  );
}
