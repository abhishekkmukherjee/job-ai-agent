import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { ApplicationStatus, Recommendation } from "../types";

/* ---------- toast ---------- */
type ToastCtx = { show: (msg: string, kind?: "info" | "error" | "success") => void };
const Ctx = createContext<ToastCtx>({ show: () => undefined });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<{ msg: string; kind: string } | null>(null);
  const show = useCallback((msg: string, kind: "info" | "error" | "success" = "info") => {
    setToast({ msg, kind });
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), toast.kind === "error" ? 7000 : 3500);
    return () => clearTimeout(t);
  }, [toast]);
  return (
    <Ctx.Provider value={{ show }}>
      {children}
      {toast && (
        <div className="toast" style={{ background: toast.kind === "error" ? "#991b1b" : toast.kind === "success" ? "#166534" : "#111827" }}>
          {toast.msg}
        </div>
      )}
    </Ctx.Provider>
  );
}
export const useToast = () => useContext(Ctx);

/* ---------- formatting ---------- */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
export function formatSalary(min: number | null, max: number | null, currency: string): string {
  if (min == null && max == null) return "";
  const fmt = (n: number) => (n >= 100000 ? `${(n / 100000).toFixed(n >= 1000000 ? 0 : 1)}L` : n >= 1000 ? `${Math.round(n / 1000)}k` : String(n));
  const c = currency ? `${currency} ` : "";
  if (min != null && max != null) return `${c}${fmt(min)} - ${fmt(max)}`;
  return `${c}${fmt((min ?? max) as number)}`;
}
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 3600) return `${Math.max(1, Math.round(diff / 60))}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

/* ---------- badges ---------- */
export function ScoreBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return <span className="score score-none">not scored</span>;
  const cls = score >= 75 ? "score-high" : score >= 60 ? "score-mid" : "score-low";
  return <span className={`score ${cls}`}>{score}%</span>;
}

export function RecommendationBadge({ value }: { value: Recommendation | string | null | undefined }) {
  if (!value) return null;
  const map: Record<string, string> = { APPLY: "badge-success", REVIEW: "badge-warning", LOW_PRIORITY: "badge-info", REJECT: "badge-danger" };
  return <span className={`badge ${map[value] || ""}`}>{value.replace("_", " ")}</span>;
}

export function StatusBadge({ status }: { status: ApplicationStatus | string }) {
  const map: Record<string, string> = {
    DISCOVERED: "", SHORTLISTED: "badge-info", APPROVED: "badge-primary", PREPARING: "badge-warning",
    READY_TO_APPLY: "badge-warning", APPLIED: "badge-success", INTERVIEW: "badge-success", OFFER: "badge-success",
    REJECTED: "badge-danger", WITHDRAWN: "",
  };
  return <span className={`badge ${map[status] || ""}`}>{status.replace(/_/g, " ")}</span>;
}

export function PipelineBadge({ status, reason }: { status: string; reason?: string }) {
  const map: Record<string, string> = { ANALYZED: "badge-success", PENDING_ANALYSIS: "badge-info", NEW: "", REJECTED_BY_RULES: "badge-danger", REJECTED_BY_AI_FILTER: "badge-danger", ANALYSIS_FAILED: "badge-danger" };
  return (
    <span className={`badge ${map[status] || ""}`} title={reason || ""}>
      {status.replace(/_/g, " ").toLowerCase()}
    </span>
  );
}

/* ---------- states ---------- */
export const Loading = ({ text = "Loading..." }: { text?: string }) => <div className="loading">{text}</div>;
export const Empty = ({ children }: { children: ReactNode }) => <div className="empty">{children}</div>;
export const ErrorAlert = ({ error }: { error: string | null }) => (error ? <div className="alert alert-error">{error}</div> : null);

/* ---------- chip input for string lists ---------- */
export function ChipInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const parts = draft.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length) onChange([...value, ...parts.filter((p) => !value.includes(p))]);
    setDraft("");
  };
  return (
    <div className="chip-input">
      {value.map((v, i) => (
        <span className="chip" key={`${v}-${i}`}>
          {v}
          <button type="button" onClick={() => onChange(value.filter((_, j) => j !== i))} aria-label={`remove ${v}`}>
            x
          </button>
        </span>
      ))}
      <input
        value={draft}
        placeholder={placeholder || "type and press Enter"}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            add();
          } else if (e.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={add}
      />
    </div>
  );
}

/* ---------- async helper ---------- */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(e.message || String(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1), setData };
}
