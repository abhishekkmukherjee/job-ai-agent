import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import JobCard from "../components/JobCard";
import { Empty, ErrorAlert, Loading, useAsync, useToast } from "../components/common";
import type { JobSummary } from "../types";

const RECS = ["APPLY", "REVIEW", "LOW_PRIORITY", "REJECT"];
const REMOTE = ["remote", "hybrid", "onsite"];
const APP_STATUSES = ["SHORTLISTED", "APPROVED", "PREPARING", "READY_TO_APPLY", "APPLIED", "INTERVIEW", "OFFER", "REJECTED"];

export default function JobsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [busyId, setBusyId] = useState<number | null>(null);

  const get = (k: string) => params.get(k) || "";
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    if (k !== "page") next.delete("page");
    setParams(next);
  };
  const page = Number(get("page") || 1);
  const query = {
    min_score: get("min_score"), q: get("q"), role: get("role"), location: get("location"), remote: get("remote"),
    company: get("company"), source: get("source"), recommendation: get("recommendation"),
    application_status: get("application_status"), include_rejected: get("include_rejected") === "true",
    include_dismissed: get("include_dismissed") === "true", only_analyzed: get("only_analyzed") === "true",
    sort: get("sort") || "score", page, page_size: 20,
  };
  const { data, error, loading, reload } = useAsync(() => api.jobs(query), [params.toString()]);
  const meta = useAsync(() => api.jobsMeta(), []);

  const wrap = async (job: JobSummary, fn: () => Promise<unknown>, ok?: string) => {
    setBusyId(job.id);
    try {
      await fn();
      if (ok) toast.show(ok, "success");
      reload();
    } catch (e: any) {
      toast.show(e.message, "error");
    } finally {
      setBusyId(null);
    }
  };
  const analyze = (job: JobSummary) => wrap(job, () => api.analyzeJob(job.id, job.match_score != null), "Analysis complete");
  const dismiss = (job: JobSummary) => wrap(job, () => api.updateJob(job.id, { user_action: "DISMISSED" }), "Job dismissed");
  const tailor = (job: JobSummary) =>
    wrap(job, async () => {
      const r = await api.tailorResume(job.id);
      navigate(`/applications/${r.application_id}`);
    });
  const prepare = async (job: JobSummary) => {
    if (job.application_id) return navigate(`/applications/${job.application_id}`);
    await wrap(job, async () => {
      const app = await api.createApplication(job.id, "APPROVED");
      navigate(`/applications/${app.id}`);
    });
  };

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Jobs</h1>
          <div className="sub">{data ? `${data.total} jobs` : ""}</div>
        </div>
        <button className="btn" onClick={reload}>Refresh</button>
      </div>
      <div className="filters">
        <input type="text" placeholder="Search title / company" value={get("q")} onChange={(e) => set("q", e.target.value)} />
        <input type="text" placeholder="Role contains" value={get("role")} onChange={(e) => set("role", e.target.value)} />
        <input type="text" placeholder="Location" value={get("location")} onChange={(e) => set("location", e.target.value)} />
        <input type="text" placeholder="Company" value={get("company")} onChange={(e) => set("company", e.target.value)} list="companies" />
        <datalist id="companies">{(meta.data?.companies || []).map((c) => <option key={c} value={c} />)}</datalist>
        <select value={get("min_score")} onChange={(e) => set("min_score", e.target.value)}>
          <option value="">Any score</option>
          {[90, 75, 60, 40].map((s) => <option key={s} value={s}>{s}%+</option>)}
        </select>
        <select value={get("recommendation")} onChange={(e) => set("recommendation", e.target.value)}>
          <option value="">Any recommendation</option>
          {RECS.map((r) => <option key={r} value={r}>{r.replace("_", " ")}</option>)}
        </select>
        <select value={get("remote")} onChange={(e) => set("remote", e.target.value)}>
          <option value="">Any work mode</option>
          {REMOTE.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <select value={get("source")} onChange={(e) => set("source", e.target.value)}>
          <option value="">Any source</option>
          {(meta.data?.sources || []).map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={get("application_status")} onChange={(e) => set("application_status", e.target.value)}>
          <option value="">Any application status</option>
          {APP_STATUSES.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
        </select>
        <select value={get("sort") || "score"} onChange={(e) => set("sort", e.target.value)}>
          <option value="score">Sort: match score</option>
          <option value="newest">Sort: newest found</option>
          <option value="posted">Sort: recently posted</option>
        </select>
        <label className="inline small"><input type="checkbox" checked={get("only_analyzed") === "true"} onChange={(e) => set("only_analyzed", e.target.checked ? "true" : "")} /> analyzed only</label>
        <label className="inline small"><input type="checkbox" checked={get("include_rejected") === "true"} onChange={(e) => set("include_rejected", e.target.checked ? "true" : "")} /> show filtered-out</label>
        <label className="inline small"><input type="checkbox" checked={get("include_dismissed") === "true"} onChange={(e) => set("include_dismissed", e.target.checked ? "true" : "")} /> show dismissed</label>
        {params.toString() && <button className="btn btn-sm" onClick={() => setParams(new URLSearchParams())}>Clear</button>}
      </div>
      <ErrorAlert error={error} />
      {loading && !data ? (
        <Loading />
      ) : !data || data.items.length === 0 ? (
        <Empty>No jobs match these filters. Run a search from the dashboard to discover new jobs.</Empty>
      ) : (
        <div className="job-list">
          {data.items.map((j) => (
            <JobCard key={j.id} job={j} busy={busyId === j.id} onAnalyze={analyze} onTailor={tailor} onPrepare={prepare} onDismiss={dismiss} />
          ))}
        </div>
      )}
      {data && totalPages > 1 && (
        <div className="pagination">
          <button className="btn btn-sm" disabled={page <= 1} onClick={() => set("page", String(page - 1))}>Prev</button>
          <span className="muted small">page {page} / {totalPages}</span>
          <button className="btn btn-sm" disabled={page >= totalPages} onClick={() => set("page", String(page + 1))}>Next</button>
        </div>
      )}
    </div>
  );
}
