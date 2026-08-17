"use client";

import { useEffect } from "react";
import { useAppStore } from "@/stores/app-store";
import { LoginScreen } from "@/components/auth/login-screen";
import { ChangePasswordScreen } from "@/components/auth/change-password-screen";
import { AppShell } from "@/components/layout/app-shell";
import { DashboardView } from "@/components/views/dashboard-view";
import { CreateEntryView } from "@/components/views/create-entry-view";
import { EditEntryView } from "@/components/views/edit-entry-view";
import { UsersView } from "@/components/views/users-view";
import { Loader2 } from "lucide-react";

export default function Home() {
  const status = useAppStore((s) => s.status);
  const user = useAppStore((s) => s.user);
  const view = useAppStore((s) => s.view);
  const refresh = useAppStore((s) => s.refresh);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Root wrapper keeps the footer pinned to the bottom of the viewport on
  // short pages, and pushes it down naturally when content overflows. The
  // content area is itself a flex column so the auth screens can `flex-1`
  // to vertically center while the footer stays glued to the bottom.
  return (
    <div className="flex min-h-screen flex-col">
      <main className="flex flex-1 flex-col px-4 py-6 sm:px-5 sm:py-8">
        {status === "loading" ? (
          <div className="flex flex-1 items-center justify-center text-[#9bb4c7]">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            Sitzung wird geladen…
          </div>
        ) : status === "unauthenticated" || !user ? (
          <LoginScreen />
        ) : user.mustChangePassword ? (
          <ChangePasswordScreen />
        ) : (
          <AppShell activeView={view}>
            {view === "dashboard" ? <DashboardView /> : null}
            {view === "create-entry" ? <CreateEntryView /> : null}
            {view === "edit-entry" ? <EditEntryView /> : null}
            {view === "users" ? <UsersView /> : null}
          </AppShell>
        )}
      </main>

      <footer className="mt-auto border-t border-[rgba(145,168,189,0.15)] bg-[rgba(7,19,29,0.6)] px-5 py-4 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1200px] flex-col items-center justify-between gap-2 text-center text-xs text-[#9bb4c7] sm:flex-row sm:text-left">
          <span>
            © {new Date().getFullYear()} Mint Week Tagebuch —
            Einträge &amp; Nutzerkonten in einer Datenbank.
          </span>
          <span className="flex items-center gap-1.5">
            Passwörter werden bcrypt-gehasht gespeichert.
          </span>
        </div>
      </footer>
    </div>
  );
}
