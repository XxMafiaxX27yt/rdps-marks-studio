// Shared app state (kept in memory only - marks are never stored in the browser).
export const S = {
  route: "school",
  step: 1,
  engineReady: false,
  version: "",
  files: null,          // from api.state()
  summary: null,        // from api.analyze()
  view: { cls: null, exam: null, section: "All" },
  tab: "overview",
  issuesFilter: "error",
  board: null,
  chat: [],
  pendingCommand: null,
  settings: null,
  rcStudent: null,
  rcExam: null,
};

const LS = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode - fine */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};
export { LS };

export const prefs = LS.get("rdps.prefs", { theme: null, aiUnderstanding: true, voiceLang: "en", macros: true });
export function savePrefs() { LS.set("rdps.prefs", prefs); }
