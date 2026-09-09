import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import {
  ErrorAlert,
  Loading,
  PipelineBadge,
  RecommendationBadge,
  ScoreBadge,
  StatusBadge,
  formatDate,
  formatSalary,
  useAsync,
  useToast,
} from "../components/common";

export default function JobDetailPage() {
  const { id } = useParams();
  const jobId = Number(id);
  const navigate = useNavigate();
  const toast = useToast();
  const { data: job, error, loading, reload } = useAsync(() => api.job(jobId), [jobId]);
  const [busy, setBusy] = useState<string | null>(null);

  const run = async (name: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(name);
    try {
      await fn();
      if (ok) toast.show(ok, "success");
      reload();
    } catch (e: any) {
      toast.show(e.message, "error");
    } finally {
      setBusy(null);
    }
  };

  if (loading && !job) return <Loading />;
  if (error) return <ErrorAlert error={error} />;
  if (!job) return null;
  const a = job.analysis;
  const salary = formatSalary(job.salary_min, job.salary_max, job.salary_currency);

  const prepare = async () => {
    if (job.application_id) return navigate(`/applications/${job.application_id}`);
    await run("prepare", async () => {
      const app = await api.createApplication(job.id, "APPROVED");
      navigate(`/applications/${app.id}`);
    });
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <Link to="/jobs" className="small">&larr; Jobs</Link>
          <h1 style={{ marginTop: 4 }}>{job.title}</h1>
          <div className="sub">
            {job.company} {job.location ? ` / ${job.location}` : ""} {salary ? ` / ${salary}` : ""}
          </div>
          <div className="inline mt">
            <span className="badge">{job.source}</span>
            {job.remote_type !== "unknown" && <span className="badge badge-info">{job.remote_type}</span>}
            <PipelineBadge status={job.pipeline_status} reason={job.filter_reason} />
            {job.application_status && <StatusBadge status={job.application_status} />}
            {job.is_sample && <span className="badge badge-warning">sample job</span>}
            <span className="muted small">posted {formatDate(job.posted_at)} / found {formatDate(job.discovered_at)}</span>
          </div>
        </div>
        <div className="right" style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
          <ScoreBadge score={job.match_score} />
          <RecommendationBadge value={job.recommendation} />
          <div className="btn-group">
            {job.url && (
              <a className="btn" href={job.url} target="_blank" rel="noreferrer">
                View Job
              </a>
            )}
            <button className="btn" disabled={!!busy} onClick={() => run("analyze", () => api.analyzeJob(job.id, job.match_score != null), "Analysis complete")}>
              {busy === "analyze" ? "Analyzing..." : job.match_score == null ? "Analyze" : "Re-analyze"}
            </button>
            <button
              className="btn"
              disabled={!!busy}
              onClick={() =>
                run("tailor", async () => {
                  const r = await api.tailorResume(job.id);
                  navigate(`/applications/${r.application_id}`);
                })
              }
            >
              {busy === "tailor" ? "Tailoring..." : "Tailor Resume"}
            </button>
            <button className="btn btn-primary" disabled={!!busy} onClick={prepare}>
              {job.application_id ? "Open Application" : "Prepare Application"}
            </button>
            {job.user_action !== "DISMISSED" ? (
              <button className="btn" disabled={!!busy} onClick={() => run("dismiss", () => api.updateJob(job.id, { user_action: "DISMISSED" }), "Dismissed")}>
                Dismiss
              </button>
            ) : (
              <button className="btn" disabled={!!busy} onClick={() => run("restore", () => api.updateJob(job.id, { user_action: "NONE" }), "Restored")}>
                Restore
              </button>
            )}
          </div>
        </div>
      </div>

      {job.analysis_error && <div className="alert alert-error">Last analysis failed: {job.analysis_error}</div>}
      {job.pipeline_status.startsWith("REJECTED") && (
        <div className="alert alert-warning">
          This job was filtered out before AI analysis: <b>{job.filter_reason}</b>. You can still analyze it manually.
        </div>
      )}

      <div className="grid grid-2">
        <div className="card">
          <h2>Description</h2>
          <div className="description">{job.description || "No description available."}</div>
          {job.tags.length > 0 && (
            <div className="skill-list mt">
              {job.tags.map((t) => (
                <span className="badge" key={t}>
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
        <div>
          <div className="card">
            <h2>AI match analysis</h2>
            {!a ? (
              <p className="muted">Not analyzed yet. Click <b>Analyze</b> to score this job against your profile.</p>
            ) : (
              <>
                {a.summary && <p>{a.summary}</p>}
                <div className="progress-bars mb">
                  {(
                    [
                      ["Overall", a.match_score],
                      ["Role", a.role_match],
                      ["Skills", a.skill_match],
                      ["Experience", a.experience_match],
                      ["Location", a.location_match],
                      ["Salary", a.salary_match],
                    ] as [string, number][]
                  ).map(([label, v]) => (
                    <div className="bar" key={label}>
                      <span>{label}</span>
                      <div className="track">
                        <div className="fill" style={{ width: `${v}%`, background: v >= 75 ? "var(--success)" : v >= 60 ? "var(--warning)" : "var(--muted)" }} />
                      </div>
                      <span className="right">{v}</span>
                    </div>
                  ))}
                </div>
                {a.matched_skills.length > 0 && (
                  <>
                    <h3>Matched skills</h3>
                    <div className="skill-list mb">
                      {a.matched_skills.map((s) => (
                        <span className="skill" key={s}>
                          &#10003; {s}
                        </span>
                      ))}
                    </div>
                  </>
                )}
                {a.missing_requirements.length > 0 && (
                  <>
                    <h3>Missing requirements</h3>
                    <div className="skill-list mb">
                      {a.missing_requirements.map((s) => (
                        <span className="skill missing" key={s}>
                          {s}
                        </span>
                      ))}
                    </div>
                  </>
                )}
                {a.reasoning.length > 0 && (
                  <>
                    <h3>Reasoning</h3>
                    <ul className="reasoning">
                      {a.reasoning.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  </>
                )}
                {a.red_flags.length > 0 && (
                  <>
                    <h3 className="mt">Red flags</h3>
                    <ul className="reasoning">
                      {a.red_flags.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  </>
                )}
                <p className="muted small mt">
                  Confidence {(a.confidence * 100).toFixed(0)}% / model {job.analysis_model || "?"} / {formatDate(job.analyzed_at)}
                </p>
              </>
            )}
          </div>
          {Object.keys(job.filter_details || {}).length > 0 && (
            <div className="card mt">
              <h3>Rule filter details</h3>
              <pre>{JSON.stringify(job.filter_details, null, 2)}</pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
