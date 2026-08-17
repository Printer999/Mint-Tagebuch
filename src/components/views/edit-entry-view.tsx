"use client";

import { useEffect, useState } from "react";
import { api, type EntryDTO } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { EntryForm } from "./entry-form";
import { Loader2 } from "lucide-react";

export function EditEntryView() {
  const editingEntryId = useAppStore((s) => s.editingEntryId);
  const setView = useAppStore((s) => s.setView);

  const [entry, setEntry] = useState<EntryDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (editingEntryId == null) {
        setError("Kein Eintrag ausgewählt.");
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const res = await api.getEntry(editingEntryId);
        if (!cancelled) setEntry(res.entry);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Eintrag konnte nicht geladen werden.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [editingEntryId]);

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-[#9bb4c7]">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Lade Eintrag…
      </div>
    );
  }

  if (error || !entry) {
    return (
      <div className="mx-auto max-w-[700px] rounded-2xl border border-[rgba(239,126,126,0.35)] bg-[rgba(239,126,126,0.08)] p-6 text-center text-[#ffcbcb]">
        {error ?? "Eintrag nicht gefunden."}
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setView("dashboard")}
            className="text-sm font-semibold text-[#9bb4c7] underline-offset-4 hover:text-[#edf4ff] hover:underline"
          >
            Zurück zum Dashboard
          </button>
        </div>
      </div>
    );
  }

  return (
    <EntryForm
      mode="edit"
      initial={{
        id: entry.id,
        entryDate: entry.entryDate,
        highLight: entry.highLight,
        lowLight: entry.lowLight,
        rating: entry.rating,
        notes: entry.notes ?? "",
      }}
    />
  );
}
