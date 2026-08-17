"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type UserDTO, type AuthUser } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Users as UsersIcon,
  UserPlus,
  KeyRound,
  Trash2,
  Loader2,
  Check,
  ShieldCheck,
  AlertCircle,
} from "lucide-react";

const ROLES: AuthUser["role"][] = ["ADMIN", "EDITOR", "VIEWER"];

const ROLE_LABELS: Record<string, string> = {
  ADMIN: "Admin",
  EDITOR: "Editor",
  VIEWER: "Viewer",
};

const ROLE_BADGE: Record<string, string> = {
  ADMIN: "border-[rgba(246,198,108,0.4)] bg-[rgba(246,198,108,0.12)] text-[#f5d28d]",
  EDITOR: "border-[rgba(97,208,168,0.4)] bg-[rgba(97,208,168,0.12)] text-[#c8f6e4]",
  VIEWER: "border-[rgba(145,168,189,0.4)] bg-[rgba(145,168,189,0.12)] text-[#cdd9e4]",
};

interface RevealedPassword {
  userName: string;
  password: string;
}

export function UsersView() {
  const currentUser = useAppStore((s) => s.user);

  const [users, setUsers] = useState<UserDTO[]>([]);
  const [currentUserId, setCurrentUserId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create-user form state
  const [newName, setNewName] = useState("");
  const [newRole, setNewRole] = useState<AuthUser["role"]>("VIEWER");
  const [creating, setCreating] = useState(false);

  const [revealed, setRevealed] = useState<RevealedPassword | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listUsers();
      setUsers(res.users);
      setCurrentUserId(res.currentUserId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nutzer konnten nicht geladen werden.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (creating) return;
    setError(null);
    if (!newName.trim()) {
      setError("Bitte einen Namen eingeben.");
      return;
    }
    setCreating(true);
    try {
      const res = await api.createUser(newName.trim(), newRole);
      setNewName("");
      setNewRole("VIEWER");
      setRevealed({ userName: res.user.name, password: res.defaultPassword });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Anlegen fehlgeschlagen.");
    } finally {
      setCreating(false);
    }
  }

  async function handleRoleChange(user: UserDTO, role: AuthUser["role"]) {
    if (busyId) return;
    if (role === user.role) return;
    setBusyId(user.id);
    setError(null);
    try {
      await api.updateUser(user.id, { role });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Rollenänderung fehlgeschlagen.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleResetPassword(user: UserDTO) {
    if (busyId) return;
    setBusyId(user.id);
    setError(null);
    try {
      const res = await api.updateUser(user.id, { resetPassword: true });
      setRevealed({ userName: user.name, password: res.defaultPassword ?? "1234" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Passwort-Reset fehlgeschlagen.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(user: UserDTO) {
    if (busyId) return;
    setBusyId(user.id);
    setError(null);
    try {
      await api.deleteUser(user.id);
      setConfirmDeleteId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Löschen fehlgeschlagen.");
    } finally {
      setBusyId(null);
    }
  }

  const stats = useMemo(() => {
    return {
      total: users.length,
      admin: users.filter((u) => u.role === "ADMIN").length,
      editor: users.filter((u) => u.role === "EDITOR").length,
      viewer: users.filter((u) => u.role === "VIEWER").length,
    };
  }, [users]);

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-[#9bb4c7]">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Lade Nutzer…
      </div>
    );
  }

  return (
    <div className="grid gap-5">
      <section className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-[0.14em] text-[#9bb4c7]">
            Administration
          </p>
          <h1 className="text-3xl font-extrabold leading-tight text-[#edf4ff] sm:text-4xl">
            Nutzerverwaltung
          </h1>
          <p className="mt-2 text-sm text-[#9bb4c7]">
            Lege Accounts an, ändere Rollen und setze Passwörter zurück. Neue
            Accounts erhalten das Standard-Passwort{" "}
            <span className="font-semibold text-[#dffaf0]">1234</span> und
            müssen es beim ersten Login ändern.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <RolePill label="Admin" value={stats.admin} className={ROLE_BADGE.ADMIN} />
          <RolePill label="Editor" value={stats.editor} className={ROLE_BADGE.EDITOR} />
          <RolePill label="Viewer" value={stats.viewer} className={ROLE_BADGE.VIEWER} />
        </div>
      </section>

      {error ? (
        <div className="flex items-start gap-2 rounded-xl border border-[rgba(239,126,126,0.35)] bg-[rgba(239,126,126,0.08)] px-4 py-3 text-sm font-medium text-[#ffcbcb]">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      ) : null}

      {revealed ? (
        <div className="flex flex-col gap-3 rounded-2xl border border-[rgba(97,208,168,0.4)] bg-[rgba(97,208,168,0.1)] p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-[#61d0a8]" />
            <div>
              <p className="text-sm font-semibold text-[#c8f6e4]">
                Standard-Passwort für „{revealed.userName}“
              </p>
              <p className="mt-0.5 text-xs text-[#9bb4c7]">
                Teile dieses Passwort sicher mit der Person. Es muss beim ersten
                Login geändert werden.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <code className="rounded-lg border border-[rgba(97,208,168,0.3)] bg-[rgba(7,19,29,0.7)] px-3 py-1.5 text-lg font-bold tracking-widest text-[#61d0a8]">
              {revealed.password}
            </code>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setRevealed(null)}
              className="border-[rgba(145,168,189,0.25)] bg-transparent text-[#edf4ff]"
            >
              Schließen
            </Button>
          </div>
        </div>
      ) : null}

      <section className="rounded-[22px] border border-[rgba(145,168,189,0.2)] bg-[rgba(10,20,31,0.75)] p-4 sm:p-6">
        <div className="mb-4 flex items-center gap-2">
          <UserPlus className="h-5 w-5 text-[#61d0a8]" />
          <h2 className="text-lg font-bold text-[#edf4ff]">Neuen Nutzer anlegen</h2>
        </div>
        <form onSubmit={handleCreate} className="grid gap-4 sm:grid-cols-[1fr_auto_auto] sm:items-end">
          <div className="grid gap-2">
            <Label htmlFor="new-name" className="text-[#edf4ff]">
              Name
            </Label>
            <Input
              id="new-name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="z.B. Anna Müller"
              required
              disabled={creating}
              className="border-[rgba(148,163,184,0.18)] bg-[rgba(148,163,184,0.05)] text-[#edf4ff] placeholder:text-[#9bb4c7]/60"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="new-role" className="text-[#edf4ff]">
              Rolle
            </Label>
            <Select
              value={newRole}
              onValueChange={(v) => setNewRole(v as AuthUser["role"])}
              disabled={creating}
            >
              <SelectTrigger
                id="new-role"
                className="w-[180px] border-[rgba(148,163,184,0.18)] bg-[rgba(148,163,184,0.05)] text-[#edf4ff]"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="border-[rgba(145,168,189,0.2)] bg-[#0c1d2d] text-[#edf4ff]">
                {ROLES.map((r) => (
                  <SelectItem key={r} value={r}>
                    {ROLE_LABELS[r]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            type="submit"
            disabled={creating}
            className="h-11 gap-2 bg-gradient-to-br from-[#61d0a8] to-[#40b98d] text-[#032a1d] hover:from-[#6cdfb3] hover:to-[#48c79a]"
          >
            {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
            Anlegen
          </Button>
        </form>
        <p className="mt-3 text-xs text-[#9bb4c7]">
          Hinweis: Rollen-Übersicht — <b>Admin</b>: volle Kontrolle über Nutzer
          &amp; Einträge. <b>Editor</b>: Einträge sehen &amp; bearbeiten.{" "}
          <b>Viewer</b>: Einträge nur ansehen.
        </p>
      </section>

      <section className="rounded-[22px] border border-[rgba(145,168,189,0.2)] bg-[rgba(10,20,31,0.75)] p-4 sm:p-6">
        <div className="mb-4 flex items-center gap-2">
          <UsersIcon className="h-5 w-5 text-[#61d0a8]" />
          <h2 className="text-lg font-bold text-[#edf4ff]">Alle Nutzer</h2>
        </div>

        {users.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-[rgba(148,163,184,0.2)] p-6 text-center text-[#9bb4c7]">
            Noch keine Nutzer angelegt.
          </div>
        ) : (
          <div className="max-h-[32rem] overflow-y-auto mint-scroll rounded-2xl border border-[rgba(145,168,189,0.15)]">
            <table className="w-full min-w-[640px] border-collapse text-sm">
              <thead className="sticky top-0 z-10 bg-[#0c1d2d] text-left text-xs uppercase tracking-wide text-[#9bb4c7]">
                <tr>
                  <th className="px-4 py-3 font-semibold">Name</th>
                  <th className="px-4 py-3 font-semibold">Rolle</th>
                  <th className="px-4 py-3 font-semibold">Status</th>
                  <th className="px-4 py-3 font-semibold">Erstellt</th>
                  <th className="px-4 py-3 text-right font-semibold">Aktionen</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const isSelf = u.id === currentUserId;
                  const isBusy = busyId === u.id;
                  const isConfirm = confirmDeleteId === u.id;
                  return (
                    <tr
                      key={u.id}
                      className="border-t border-[rgba(145,168,189,0.15)] hover:bg-white/[0.02]"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-[#edf4ff]">{u.name}</span>
                          {isSelf ? (
                            <span className="rounded-full border border-[rgba(97,208,168,0.4)] bg-[rgba(97,208,168,0.12)] px-2 py-0.5 text-[10px] font-bold uppercase text-[#c8f6e4]">
                              Du
                            </span>
                          ) : null}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <Select
                          value={u.role}
                          onValueChange={(v) => void handleRoleChange(u, v as AuthUser["role"])}
                          disabled={isBusy || isSelf}
                        >
                          <SelectTrigger
                            className={[
                              "h-9 w-[140px] gap-2 border font-semibold",
                              u.role === "ADMIN"
                                ? "border-[rgba(246,198,108,0.4)] bg-[rgba(246,198,108,0.1)] text-[#f5d28d]"
                                : u.role === "EDITOR"
                                  ? "border-[rgba(97,208,168,0.4)] bg-[rgba(97,208,168,0.1)] text-[#c8f6e4]"
                                  : "border-[rgba(145,168,189,0.4)] bg-[rgba(145,168,189,0.1)] text-[#cdd9e4]",
                            ].join(" ")}
                          >
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent className="border-[rgba(145,168,189,0.2)] bg-[#0c1d2d] text-[#edf4ff]">
                            {ROLES.map((r) => (
                              <SelectItem key={r} value={r} disabled={isSelf && r !== "ADMIN"}>
                                {ROLE_LABELS[r]}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </td>
                      <td className="px-4 py-3">
                        {u.mustChangePassword ? (
                          <span className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(246,198,108,0.35)] bg-[rgba(246,198,108,0.1)] px-2.5 py-1 text-xs font-medium text-[#f5d28d]">
                            <KeyRound className="h-3 w-3" />
                            Passwort offen
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(97,208,168,0.35)] bg-[rgba(97,208,168,0.1)] px-2.5 py-1 text-xs font-medium text-[#c8f6e4]">
                            <Check className="h-3 w-3" />
                            Aktiv
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-[#9bb4c7]">
                        {new Date(u.createdAt).toLocaleDateString("de-DE", {
                          day: "2-digit",
                          month: "2-digit",
                          year: "numeric",
                        })}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={isBusy}
                            onClick={() => void handleResetPassword(u)}
                            className="gap-1.5 border-[rgba(246,198,108,0.3)] bg-[rgba(246,198,108,0.08)] text-[#f5d28d] hover:bg-[rgba(246,198,108,0.18)]"
                          >
                            {isBusy ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <KeyRound className="h-3.5 w-3.5" />
                            )}
                            <span className="hidden md:inline">Passwort zurücksetzen</span>
                            <span className="md:hidden">Reset</span>
                          </Button>

                          {isConfirm ? (
                            <Button
                              type="button"
                              size="sm"
                              disabled={isBusy || isSelf}
                              onClick={() => void handleDelete(u)}
                              className="gap-1.5 border border-[rgba(239,126,126,0.45)] bg-[rgba(239,126,126,0.18)] text-[#ffd7d7] hover:bg-[rgba(239,126,126,0.28)]"
                            >
                              {isBusy ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Trash2 className="h-3.5 w-3.5" />
                              )}
                              Bestätigen
                            </Button>
                          ) : (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              disabled={isBusy || isSelf}
                              onClick={() => setConfirmDeleteId(u.id)}
                              className="gap-1.5 border-[rgba(239,126,126,0.3)] bg-[rgba(239,126,126,0.08)] text-[#ffd7d7] hover:bg-[rgba(239,126,126,0.18)]"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                              <span className="hidden md:inline">Löschen</span>
                            </Button>
                          )}

                          {isConfirm ? (
                            <button
                              type="button"
                              onClick={() => setConfirmDeleteId(null)}
                              disabled={isBusy}
                              className="text-xs font-semibold text-[#9bb4c7] hover:text-[#edf4ff]"
                            >
                              Abbrechen
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

interface RolePillProps {
  label: string;
  value: number;
  className: string;
}

function RolePill({ label, value, className }: RolePillProps) {
  return (
    <div
      className={["flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm", className].join(" ")}
    >
      <span className="font-bold">{value}</span>
      <span className="font-medium">{label}</span>
    </div>
  );
}
