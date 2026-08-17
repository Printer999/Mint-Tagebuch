"use client";

import { useState } from "react";
import { useAppStore } from "@/stores/app-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, LogIn, ShieldCheck, Sparkles } from "lucide-react";

export function LoginScreen() {
  const login = useAppStore((s) => s.login);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      await login(name, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login fehlgeschlagen.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative flex flex-1 items-center justify-center px-4 py-12">
      <div className="absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-24 -left-24 h-72 w-72 rounded-full bg-[#61d0a8]/20 blur-3xl" />
        <div className="absolute -bottom-24 -right-24 h-72 w-72 rounded-full bg-[#60a5fa]/20 blur-3xl" />
      </div>

      <div className="w-full max-w-md mint-fade-up">
        <div className="rounded-3xl border border-[rgba(145,168,189,0.2)] bg-[rgba(18,38,54,0.92)] p-8 shadow-[0_24px_80px_rgba(2,6,23,0.45)] backdrop-blur-xl">
          <div className="mb-7 flex flex-col items-center text-center">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-[#61d0a8] to-[#40b98d] text-[#032a1d] shadow-lg">
              <Sparkles className="h-7 w-7" />
            </div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-[#9bb4c7]">
              Mint Week
            </div>
            <h1 className="mt-1 mint-glow text-2xl font-extrabold tracking-tight text-[#61d0a8]">
              Tagebuch
            </h1>
            <p className="mt-2 text-sm text-[#9bb4c7]">
              Melde dich an, um deine Einträge zu sehen und zu bearbeiten.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="name" className="text-[#edf4ff]">
                Name
              </Label>
              <Input
                id="name"
                name="name"
                autoComplete="username"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="z.B. TheHacker"
                required
                autoFocus
                disabled={submitting}
                className="border-[rgba(148,163,184,0.18)] bg-[rgba(148,163,184,0.05)] text-[#edf4ff] placeholder:text-[#9bb4c7]/60"
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="password" className="text-[#edf4ff]">
                Passwort
              </Label>
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
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
                <LogIn className="h-4 w-4" />
              )}
              Anmelden
            </Button>
          </form>

          <div className="mt-6 flex items-start gap-2 rounded-xl border border-[rgba(97,208,168,0.2)] bg-[rgba(97,208,168,0.08)] px-3 py-2.5 text-xs text-[#9bb4c7]">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-[#61d0a8]" />
            <span>
              Beim ersten Login wirst du aufgefordert, dein Passwort zu ändern.
              Neue Accounts erhalten standardmäßig das Passwort{" "}
              <span className="font-semibold text-[#dffaf0]">1234</span>.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
