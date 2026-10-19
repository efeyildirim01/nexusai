import type { Metadata } from "next";
import Link from "next/link";
import { AuthShell } from "@/components/auth-shell";
import { SignInForm } from "./sign-in-form";

export const metadata: Metadata = { title: "Sign in" };

export default function SignInPage() {
  return (
    <AuthShell
      title="Sign in"
      subtitle="Use your workspace name, email and password."
      footer={
        <>
          New to NexusAI?{" "}
          <Link href="/sign-up" className="font-medium text-indigo-600 hover:text-indigo-500">
            Create a workspace
          </Link>
        </>
      }
    >
      <SignInForm />
    </AuthShell>
  );
}
