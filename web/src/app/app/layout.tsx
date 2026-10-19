import { AppShell } from "@/components/app-shell";

// The signed-in area renders on the client once the session's profile has loaded (all
// data comes through the cookie-authenticated BFF), so there is no static shell for
// these pages to validate for instant navigation.
export const instant = false;

export default function AppLayout({ children }: LayoutProps<"/app">) {
  return <AppShell>{children}</AppShell>;
}
