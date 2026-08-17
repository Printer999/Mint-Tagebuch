"use client";

import { useState } from "react";
import { useAppStore } from "@/stores/app-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { KeyRound, Loader2, ShieldAlert, Check } from "lucide-react";

export function ChangePasswordScreen() {
  const user = useAppStore((s) => s.user);
  const changePassword = useAppStore((s) => s.changePassword);
  const logout = useAppStore((s) => s.logout);

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setError(null);

    if (!current || !next || !confirm) {
      setError("Bitte alle Felder ausfüllen.");
      return;
    }
    if (next !== confirm) {
      setError("Die neuen Passwörter stimmen nicht überein.");
      return;
    }
    if (next.length < 4) {
      setError("Das neue Passwort muss mindestens 4 Zeichen lang sein.");
      return;
    }
    if (next === "1234") {
      setError("Das neue Passwort darf nicht 1234 sein.");
      return;
    }

    setSubmitting(true);
    try {
      await changePassword(current, next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Passwortänderung fehlgeschlagen.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative flex flex-1 items-center justify-center px-4 py-12">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-24 left-1/2 h-72 w-72 -translate-x-1/2 rounded-full bg-[#f6c66c]/15 blur-3xl" />
      </div>

      <div className="w-full max-w-md mint-fade-up">
        <div className="rounded-3xl border border-[rgba(246,198,108,0.25)] bg-[rgba(18,38,54,0.92)] p-8 shadow-[0_24px_80px_rgba(2,6,23,0.45)] backdrop-blur-xl">
          <div className="mb-6 flex flex-col items-center text-center">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-[#f6c66c] to-[#d99a3f] text-[#3a2400] shadow-lg">
              <KeyRound className="h-7 w-7" />
            </div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-[#9bb4c7]">
              Erstinrichtung
            </div>
            <h1 className="mt-1 text-2xl font-extrabold tracking-tight text-[#edf4ff]">
              Passwort ändern
            </h1>
            <p className="mt-2 text-sm text-[#9bb4c7]">
              Hallo {user?.name ?? ""}, bitte ändere dein Passwort beim ersten
              Login, bevor du das Tagebuch nutzen kannst.
            </p>
          </div>

          <div className="mb-5 flex items-start gap-2 rounded-xl border border-[rgba(246,198,108,0.35)] bg-[rgba(246,198,108,0.08)] px-3 py-2.5 text-xs text-[#f5d28d]">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              Aus Sicherheitsgründen muss das Passwort vor der ersten Nutzung
              geändert werden. Wähle ein Passwort ungleich <b>1234</b>.
            </span>
          </div>

          <form onSubmit={handleSubmit} className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="current" className="text-[#edf4ff]">
                Aktuelles Passwort
              </Label>
              <Input
                id="current"
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                placeholder="••••••••"
                required
                autoFocus
                disabled={submitting}
                className="border-[rgba(148,163,184,0.18)] bg-[rgba(148,163,184,0.05)] text-[#edf4ff] placeholder:text-[#9bb4c7]/60"
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="next" className="text-[#edf4ff]">
                Neues Passwort
              </Label>
              <Input
                id="next"
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                placeholder="mindestens 4 Zeichen"
                required
                disabled={submitting}
                className="border-[rgba(148,163,184,0.18)] bg-[rgba(148,163,184,0.05)] text-[#edf4ff] placeholder:text-[#9bb4c7]/60"
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="confirm" className="text-[#edf4ff]">
                Neues Passwort wiederholen
              </Label>
              <Input
                id="confirm"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="••••••••"
                required
                disabled={submitting}
                className="border-[rgba(148,163,184,0.18)] bg-[rgba(148,163,184,0.05)] text-[#edf4ff] placeholder:text-[#9bb4c7]/60"
              />
            </div>

            {error ? (
              <div className="rounded-xl border border-[rgba(239,126,126,0.35)] bg-[rgba(239,126,126,0.08)] px-4 py-3 text-sm font-medium text-[#ffcbcb]">
                {error}
              </div>
            ) : null}

            <Button
              type="submit"
              disabled={submitting}
              className="mt-2 h-11 w-full gap-2 bg-gradient-to-br from-[#61d0a8] to-[#40b98d] text-[#032a1d] hover:from-[#6cdfb3] hover:to-[#48c79a]"
            >
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Check className="h-4 w-4" />
              )}
              Passwort speichern
            </Button>
          </form>

          <button
            type="button"
            onClick={() => void logout()}
            disabled={submitting}
            className="mt-4 w-full text-center text-xs font-semibold text-[#9bb4c7] underline-offset-4 hover:text-[#edf4ff] hover:underline disabled:opacity-50"
          >
            Abmelden
          </button>
        </div>
      </div>
    </div>
  );
}
