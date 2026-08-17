"use client";

import { create } from "zustand";
import { api, type AuthUser } from "@/lib/api";

export type AppView =
  | "dashboard"
  | "create-entry"
  | "edit-entry"
  | "users";

interface AppState {
  user: AuthUser | null;
  status: "loading" | "authenticated" | "unauthenticated";

  // Client-side view routing (everything lives on the single `/` route).
  view: AppView;
  editingEntryId: number | null;

  // Track whether the user has just changed their password so the dashboard
  // can show a brief confirmation toast.
  lastChangedAt: number | null;

  setUser: (user: AuthUser | null) => void;
  refresh: () => Promise<void>;
  login: (name: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  changePassword: (current: string, next: string) => Promise<void>;

  setView: (view: AppView) => void;
  startEdit: (id: number) => void;
}

export const useAppStore = create<AppState>((set) => ({
  user: null,
  status: "loading",
  view: "dashboard",
  editingEntryId: null,
  lastChangedAt: null,

  setUser: (user) =>
    set({
      user,
      status: user ? "authenticated" : "unauthenticated",
    }),

  refresh: async () => {
    try {
      const { user } = await api.me();
      set({
        user,
        status: user ? "authenticated" : "unauthenticated",
      });
    } catch {
      set({ user: null, status: "unauthenticated" });
    }
  },

  login: async (name, password) => {
    const { user } = await api.login(name, password);
    set({
      user,
      status: "authenticated",
      view: "dashboard",
      editingEntryId: null,
    });
  },

  logout: async () => {
    try {
      await api.logout();
    } finally {
      set({
        user: null,
        status: "unauthenticated",
        view: "dashboard",
        editingEntryId: null,
      });
    }
  },

  changePassword: async (current, next) => {
    const { user } = await api.changePassword(current, next);
    set({ user, lastChangedAt: Date.now() });
  },

  setView: (view) => set({ view, editingEntryId: null }),

  startEdit: (id) => set({ view: "edit-entry", editingEntryId: id }),
}));
