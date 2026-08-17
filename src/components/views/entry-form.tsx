"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { RatingPicker } from "@/components/entry/rating-picker";
import { ArrowLeft, Loader2, Save } from "lucide-react";

interface EntryFormProps {
  mode: "create" | "edit";
  initial?: {
    id: number;
    entryDate: string;
    highLight: string;
    lowLight: string;
    rating: number;
    notes: string;
  };
}

function todayISO(): string {
  const d = new Date();
  const tz = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - tz).toISOString().slice(0, 10);
}

export function EntryForm({ mode, initial }: EntryFormProps) {
  const setView = useAppStore((s) => s.setView);

  const [entryDate, setEntryDate] = useState(
    initial?.entryDate ?? todayISO(),
  );
  const [rating, setRating] = useState(initial?.rating ?? 3);
  const [highLight, setHighLight] = useState(initial?.highLight ?? "");
  const [lowLight, setLowLight] = useState(initial?.lowLight ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");

  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setError(null);

    if (!entryDate || !highLight.trim() || !lowLight.trim()) {
      setError("Bitte Datum, High und Low Light ausfüllen.");
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        entryDate,
        highLight: highLight.trim(),
        lowLight: lowLight.trim(),
        rating,
        notes: notes.trim(),
      };
      if (mode === "create") {
        await api.createEntry(payload);
      } else if (initial) {
        await api.updateEntry(initial.id, payload);
      }
      setView("dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Speichern fehlgeschlagen.");
    } finally {
      setSubmitting(false);
    }
  }

  const title = mode === "create" ? "Tagebucheintrag erstellen" : "Eintrag bearbeiten";
  const eyebrow = mode === "create" ? "Neuer Eintrag" : "Bearbeiten";
  const submitLabel = mode === "create" ? "Eintrag speichern" : "Änderungen speichern";

  return (
    <div className="mx-auto grid w-full max-w-[900px] gap-5">
      <section className="flex items-center justify-between gap-3">
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-[0.14em] text-[#9bb4c7]">
            {eyebrow}
          </p>
          <h1 className="text-2xl font-extrabold leading-tight text-[#edf4ff] sm:text-3xl">
            {title}
          </h1>
        </div>
        <Button
          type="button"
          variant="ghost"
          onClick={() => setView("dashboard")}
          className="gap-2 text-[#9bb4c7] hover:bg-white/[0.04] hover:text-[#edf4ff]"
        >
          <ArrowLeft className="h-4 w-4" />
          <span className="hidden sm:inline">Zurück</span>
        </Button>
      </section>

      <form
        onSubmit={handleSubmit}
        className="grid gap-5 rounded-[22px] border border-[rgba(145,168,189,0.2)] bg-[rgba(10,20,31,0.75)] p-4 sm:p-6"
      >
        <div className="grid gap-5 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="entry_date" className="text-[#edf4ff]">
              Datum
            </Label>
            <Input
              id="entry_date"
              type="date"
              value={entryDate}
              onChange={(e) => setEntryDate(e.target.value)}
              required
              disabled={submitting}
              className="border-[rgba(148,163,184,0.18)] bg-[rgba(148,163,184,0.05)] text-[#edf4ff]"
            />
          </div>

          <div className="grid gap-2">
            <Label className="text-[#edf4ff]">Bewertung</Label>
            <div className="flex items-center gap-3 py-1">
              <RatingPicker
                value={rating}
                onChange={setRating}
                disabled={submitting}
              />
            </div>
          </div>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="high_light" className="text-[#edf4ff]">
            High Light
          </Label>
          <Textarea
            id="high_light"
            rows={3}
            placeholder="Was war heute besonders gut?"
            value={highLight}
            onChange={(e) => setHighLight(e.target.value)}
            required
            disabled={submitting}
            className="min-h-[90px] resize-y border-[rgba(148,163,184,0.18)] bg-[rgba(148,163,184,0.05)] text-[#edf4ff] placeholder:text-[#9bb4c7]/60"
          />
        </div>

        <div className="grid gap-2">
          <Label htmlFor="low_light" className="text-[#edf4ff]">
            Low Light
          </Label>
          <Textarea
            id="low_light"
            rows={3}
            placeholder="Was war heute schwierig oder weniger gut?"
            value={lowLight}
            onChange={(e) => setLowLight(e.target.value)}
            required
            disabled={submitting}
            className="min-h-[90px] resize-y border-[rgba(148,163,184,0.18)] bg-[rgba(148,163,184,0.05)] text-[#edf4ff] placeholder:text-[#9bb4c7]/60"
          />
        </div>

        <div className="grid gap-2">
          <Label htmlFor="notes" className="text-[#edf4ff]">
            Notizen
          </Label>
          <Textarea
            id="notes"
            rows={4}
            placeholder="Zusätzliche Gedanken, Beobachtungen, Eindrücke..."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            disabled={submitting}
            className="min-h-[110px] resize-y border-[rgba(148,163,184,0.18)] bg-[rgba(148,163,184,0.05)] text-[#edf4ff] placeholder:text-[#9bb4c7]/60"
          />
        </div>

        {error ? (
          <div className="rounded-xl border border-[rgba(239,126,126,0.35)] bg-[rgba(239,126,126,0.08)] px-4 py-3 text-sm font-medium text-[#ffcbcb]">
            {error}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-3 pt-1">
          <Button
            type="submit"
            disabled={submitting}
            className="gap-2 bg-gradient-to-br from-[#61d0a8] to-[#40b98d] text-[#032a1d] hover:from-[#6cdfb3] hover:to-[#48c79a]"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            {submitLabel}
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => setView("dashboard")}
            disabled={submitting}
            className="text-[#9bb4c7] hover:bg-white/[0.04] hover:text-[#edf4ff]"
          >
            Zurück zum Dashboard
          </Button>
        </div>
      </form>
    </div>
  );
}
