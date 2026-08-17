"use client";

import { useAppStore, type AppView } from "@/stores/app-store";
import { Button } from "@/components/ui/button";
import { LayoutDashboard, Plus, Users, LogOut, Sparkles } from "lucide-react";

interface AppShellProps {
  children: React.ReactNode;
  activeView: AppView;
}

const ROLE_LABELS: Record<string, string> = {
  ADMIN: "Admin",
  EDITOR: "Editor",
  VIEWER: "Viewer",
};

const ROLE_COLORS: Record<string, string> = {
  ADMIN: "border-[rgba(246,198,108,0.4)] bg-[rgba(246,198,108,0.12)] text-[#f5d28d]",
  EDITOR: "border-[rgba(97,208,168,0.4)] bg-[rgba(97,208,168,0.12)] text-[#c8f6e4]",
  VIEWER: "border-[rgba(145,168,189,0.4)] bg-[rgba(145,168,189,0.12)] text-[#cdd9e4]",
};

/**
 * Application chrome shared by every authenticated view: a top bar with the
 * brand, role-aware navigation and the logged-in user pill. The footer is
 * sticky to the bottom on short pages and pushed down on long pages thanks
 * to the `min-h-screen flex flex-col` layout in the page wrapper.
 */
export function AppShell({ children, activeView }: AppShellProps) {
  const user = useAppStore((s) => s.user);
  const setView = useAppStore((s) => s.setView);
  const logout = useAppStore((s) => s.logout);

  const isAdmin = user?.role === "ADMIN";
  const canEdit = user?.role === "ADMIN" || user?.role === "EDITOR";

  const navItems: { view: AppView; label: string; icon: React.ReactNode; show: boolean }[] = [
    {
      view: "dashboard",
      label: "Dashboard",
      icon: <LayoutDashboard className="h-4 w-4" />,
      show: true,
    },
    {
      view: "create-entry",
      label: "Neuer Eintrag",
      icon: <Plus className="h-4 w-4" />,
      show: canEdit,
    },
    {
      view: "users",
      label: "Nutzerverwaltung",
      icon: <Users className="h-4 w-4" />,
      show: isAdmin,
    },
  ];

  return (
    <div className="mx-auto w-full max-w-[1200px]">
      <div className="overflow-hidden rounded-[28px] border border-[rgba(145,168,189,0.2)] bg-[rgba(7,19,29,0.7)] shadow-[0_24px_80px_rgba(2,6,23,0.45)] backdrop-blur-md">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[rgba(145,168,189,0.2)] bg-[rgba(11,27,38,0.8)] px-4 py-3.5 sm:px-6">
          <button
            type="button"
            onClick={() => setView("dashboard")}
            className="flex items-center gap-2 text-left"
          >
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-[#61d0a8] to-[#40b98d] text-[#032a1d]">
              <Sparkles className="h-4 w-4" />
            </span>
            <span className="text-base font-extrabold uppercase tracking-[0.08em] text-[#61d0a8]">
              Mint Week
            </span>
          </button>

          <nav className="flex flex-wrap items-center gap-1.5">
            {navItems
              .filter((item) => item.show)
              .map((item) => {
                const active = activeView === item.view;
                return (
                  <button
                    key={item.view}
                    type="button"
                    onClick={() => setView(item.view)}
                    className={[
                      "flex items-center gap-2 rounded-full border px-3.5 py-2 text-sm font-medium transition",
                      active
                        ? "border-[rgba(97,208,168,0.25)] bg-[rgba(97,208,168,0.12)] text-[#edf4ff]"
                        : "border-transparent bg-white/[0.02] text-[#edf4ff]/90 hover:border-[rgba(97,208,168,0.25)] hover:bg-[rgba(97,208,168,0.12)]",
                    ].join(" ")}
                  >
                    {item.icon}
                    <span className="hidden sm:inline">{item.label}</span>
                  </button>
                );
              })}
          </nav>

          <div className="flex items-center gap-2">
            <div className="hidden items-center gap-2 rounded-full border border-[rgba(145,168,189,0.2)] bg-white/[0.02] px-3 py-2 sm:flex">
              <span className="text-sm font-medium text-[#edf4ff]">
                {user?.name}
              </span>
              <span
                className={[
                  "rounded-full border px-2 py-0.5 text-xs font-bold uppercase tracking-wide",
                  ROLE_COLORS[user?.role ?? "VIEWER"],
                ].join(" ")}
              >
                {ROLE_LABELS[user?.role ?? "VIEWER"]}
              </span>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void logout()}
              className="border-[rgba(145,168,189,0.25)] bg-transparent text-[#edf4ff] hover:bg-[rgba(239,126,126,0.12)] hover:text-[#ffcbcb]"
            >
              <LogOut className="h-4 w-4" />
              <span className="hidden sm:inline">Abmelden</span>
            </Button>
          </div>
        </header>

        <main className="px-4 py-6 sm:px-6 sm:py-8">{children}</main>
      </div>
    </div>
  );
}
