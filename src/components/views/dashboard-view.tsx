"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type DashboardResponse } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { Button } from "@/components/ui/button";
import { Plus, Pencil, Trash2, Star, Loader2, BookOpen, TrendingUp, Calendar } from "lucide-react";

interface DashboardViewProps {
  onCreatedToast?: () => void;
}

export function DashboardView({ onCreatedToast }: DashboardViewProps) {
  const user = useAppStore((s) => s.user);
  const setView = useAppStore((s) => s.setView);
  const startEdit = useAppStore((s) => s.startEdit);

  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listEntries();
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Einträge konnten nicht geladen werden.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const canEdit = user?.role === "ADMIN" || user?.role === "EDITOR";

  async function handleDelete(id: number) {
    if (busyId !== null) return;
    setBusyId(id);
    try {
      await api.deleteEntry(id);
      setConfirmId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Löschen fehlgeschlagen.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-[#9bb4c7]">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Lade Einträge…
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="rounded-2xl border border-[rgba(239,126,126,0.35)] bg-[rgba(239,126,126,0.08)] p-6 text-center text-[#ffcbcb]">
        {error}
        <div className="mt-3">
          <Button variant="outline" onClick={() => void load()}>
            Erneut versuchen
          </Button>
        </div>
      </div>
    );
  }

  const summary = data?.summary;
  const entries = data?.entries ?? [];

  return (
    <div className="grid gap-5">
      {error ? (
        <div className="rounded-xl border border-[rgba(239,126,126,0.35)] bg-[rgba(239,126,126,0.08)] px-4 py-3 text-sm font-medium text-[#ffcbcb]">
          {error}
        </div>
      ) : null}

      <section className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-[0.14em] text-[#9bb4c7]">
            Dashboard
          </p>
          <h1 className="text-3xl font-extrabold leading-tight text-[#edf4ff] sm:text-4xl">
            Meine Mint-Woche
          </h1>
        </div>
        <div className="rounded-2xl border border-[rgba(97,208,168,0.22)] bg-gradient-to-br from-[rgba(97,208,168,0.16)] to-[rgba(96,165,250,0.12)] px-4 py-3 text-right">
          <span className="block text-xs uppercase tracking-wide text-[#9bb4c7]">
            Ø Bewertung
          </span>
          <strong className="text-2xl font-bold text-[#edf4ff]">
            {summary ? summary.avgRating.toFixed(1) : "0.0"}
            <span className="text-base text-[#9bb4c7]">/5</span>
          </strong>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard
          accent
          icon={<BookOpen className="h-4 w-4" />}
          label="Einträge"
          value={summary ? String(summary.totalEntries) : "0"}
          hint={
            summary && summary.firstDate
              ? `${summary.firstDate} – ${summary.lastDate ?? "—"}`
              : "Noch keine Daten"
          }
        />
        <StatCard
          icon={<TrendingUp className="h-4 w-4" />}
          label="Bestes Highlight"
          value={
            summary?.bestDay
              ? summary.bestDay.highLight.length > 35
                ? summary.bestDay.highLight.slice(0, 35) + "…"
                : summary.bestDay.highLight
              : "—"
          }
          hint={
            summary?.bestDay
              ? `${summary.bestDay.rating}/5 am ${summary.bestDay.entryDate}`
              : "Noch keine Einträge"
          }
        />
        <StatCard
          icon={<Calendar className="h-4 w-4" />}
          label="Letzter Eintrag"
          value={summary?.latest ? summary.latest.entryDate : "—"}
          hint={
            summary?.latest
              ? summary.latest.highLight.length > 40
                ? summary.latest.highLight.slice(0, 40) + "…"
                : summary.latest.highLight
              : "Noch keine Einträge"
          }
        />
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-bold text-[#edf4ff]">Letzte Tage</h2>
          {canEdit ? (
            <Button
              type="button"
              onClick={() => {
                setView("create-entry");
              }}
              className="gap-2 bg-gradient-to-br from-[#61d0a8] to-[#40b98d] text-[#032a1d] hover:from-[#6cdfb3] hover:to-[#48c79a]"
            >
              <Plus className="h-4 w-4" />
              <span className="hidden sm:inline">Neuer Eintrag</span>
              <span className="sm:hidden">Neu</span>
            </Button>
          ) : null}
        </div>

        {entries.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-[rgba(148,163,184,0.2)] bg-white/[0.02] p-8 text-center text-[#9bb4c7]">
            Noch keine Einträge.{" "}
            {canEdit ? "Füge deinen ersten Tag der Mint-Woche hinzu." : ""}
          </div>
        ) : (
          <div className="grid gap-3.5">
            {entries.map((entry) => {
              const isConfirm = confirmId === entry.id;
              return (
                <article
                  key={entry.id}
                  className="rounded-2xl border border-[rgba(145,168,189,0.2)] bg-[rgba(27,49,67,0.8)] p-4 sm:p-5"
                >
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <strong className="text-[#edf4ff]">{entry.entryDate}</strong>
                    <span className="inline-flex items-center gap-1 rounded-full border border-[rgba(246,198,108,0.35)] bg-[rgba(246,198,108,0.12)] px-2.5 py-1 text-xs font-bold text-[#f5d28d]">
                      <Star className="h-3 w-3 fill-current" />
                      {entry.rating}/5
                    </span>
                  </div>

                  <div className="grid gap-3">
                    <div>
                      <label className="text-xs uppercase tracking-wide text-[#9bb4c7]">
                        High Light
                      </label>
                      <p className="mt-1 leading-relaxed text-[#edf4ff]">{entry.highLight}</p>
                    </div>
                    <div>
                      <label className="text-xs uppercase tracking-wide text-[#9bb4c7]">
                        Low Light
                      </label>
                      <p className="mt-1 leading-relaxed text-[#edf4ff]">{entry.lowLight}</p>
                    </div>
                    {entry.notes ? (
                      <div>
                        <label className="text-xs uppercase tracking-wide text-[#9bb4c7]">
                          Notizen
                        </label>
                        <p className="mt-1 leading-relaxed text-[#edf4ff]">{entry.notes}</p>
                      </div>
                    ) : null}
                  </div>

                  {canEdit ? (
                    <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
                      {isConfirm ? (
                        <>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={busyId === entry.id}
                            onClick={() => setConfirmId(null)}
                            className="border-[rgba(145,168,189,0.25)] bg-transparent text-[#edf4ff]"
                          >
                            Abbrechen
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            disabled={busyId === entry.id}
                            onClick={() => void handleDelete(entry.id)}
                            className="gap-1.5 border border-[rgba(239,126,126,0.45)] bg-[rgba(239,126,126,0.15)] text-[#ffd7d7] hover:bg-[rgba(239,126,126,0.25)]"
                          >
                            {busyId === entry.id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Trash2 className="h-3.5 w-3.5" />
                            )}
                            Wirklich löschen
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => startEdit(entry.id)}
                            className="gap-1.5 border-[rgba(97,208,168,0.3)] bg-[rgba(97,208,168,0.08)] text-[#dffaf0] hover:bg-[rgba(97,208,168,0.18)]"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                            Bearbeiten
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => setConfirmId(entry.id)}
                            className="gap-1.5 border-[rgba(239,126,126,0.3)] bg-[rgba(239,126,126,0.08)] text-[#ffd7d7] hover:bg-[rgba(239,126,126,0.18)]"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            Löschen
                          </Button>
                        </>
                      )}
                    </div>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
      </section>

      {canEdit ? (
        <div className="mt-2 flex justify-center border-t border-[rgba(145,168,189,0.15)] pt-6">
          <Button
            type="button"
            onClick={() => {
              onCreatedToast?.();
              setView("create-entry");
            }}
            className="gap-2 bg-gradient-to-br from-[#61d0a8] to-[#40b98d] px-6 text-[#032a1d] hover:from-[#6cdfb3] hover:to-[#48c79a]"
          >
            <Plus className="h-4 w-4" />
            Neuer Eintrag
          </Button>
        </div>
      ) : null}
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: string;
  hint: string;
  icon: React.ReactNode;
  accent?: boolean;
}

function StatCard({ label, value, hint, icon, accent }: StatCardProps) {
  return (
    <div
      className={[
        "flex min-h-[140px] flex-col rounded-2xl border p-4",
        accent
          ? "border-[rgba(97,208,168,0.3)] bg-gradient-to-b from-[rgba(97,208,168,0.14)] to-[rgba(18,38,54,0.9)]"
          : "border-[rgba(145,168,189,0.2)] bg-gradient-to-b from-[rgba(18,38,54,0.9)] to-[rgba(11,27,38,0.75)]",
      ].join(" ")}
    >
      <div className="flex items-center gap-2 text-[#9bb4c7]">
        {icon}
        <span className="text-xs font-semibold uppercase tracking-[0.08em]">
          {label}
        </span>
      </div>
      <strong className="mt-3 text-2xl font-bold leading-tight text-[#edf4ff]">
        {value}
      </strong>
      <small className="mt-auto pt-3 text-xs leading-relaxed text-[#9bb4c7]">
        {hint}
      </small>
    </div>
  );
}
