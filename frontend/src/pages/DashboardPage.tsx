import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import JobCard from "../components/JobCard";
import { Empty, ErrorAlert, Loading, StatusBadge, formatDateTime, useAsync, useToast } from "../components/common";
import type { JobSummary } from "../types";

export default function DashboardPage() {
  const { data, error, loading, reload } = useAsync(() => api.dashboard(), []);
  const [searching, setSearching] = useState(false);
  const toast = useToast();
  const navigate = useNavigate();

  const runSearch = async () => {
    setSearching(true);
    try {
      const r = await api.searchJobs({ analyze: true, notify: false });
      toast.show(`${r.message} (run #${r.run_id}). Refresh in a minute.`, "success");
    } catch (e: any) {
      toast.show(e.message, "error");
    } finally {
      setSearching(false);
    }
  };

  const prepare = async (job: JobSummary) => {
    if (job.application_id) return navigate(`/applications/${job.application_id}`);
    try {
      const app = await api.createApplication(job.id, "APPROVED");
      navigate(`/applications/${app.id}`);
    } catch (e: any) {
      toast.show(e.message, "error");
    }
  };

  if (loading && !data) return <Loading />;
  if (error) return <ErrorAlert error={error} />;
  if (!data) return null;
  const c = data.counts;
  const ai = data.ai as { configured_providers?: string[] } | undefined;
  const run = data.last_run;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Today&apos;s Search</h1>
          <div className="sub">
            {run ? (
              <>
                Last run #{run.id} ({run.trigger}) {run.status.toLowerCase()} at {formatDateTime(run.started_at)}
                {run.stats && typeof run.stats.new_jobs === "number" ? ` - ${run.stats.new_jobs} new jobs` : ""}
              </>
            ) : (
              "No search has been run yet."
            )}
          </div>
        </div>
        <div className="btn-group">
          <button className="btn" onClick={reload}>Refresh</button>
          <button className="btn btn-primary" onClick={runSearch} disabled={searching}>
            {searching ? "Starting..." : "Search jobs now"}
          </button>
        </div>
      </div>

      {ai && ai.configured_providers && ai.configured_providers.length === 0 && (
        <div className="alert alert-warning">
          No AI provider configured. Add GEMINI_API_KEY, GROQ_API_KEY or OPENROUTER_API_KEY to <code>.env</code> to enable job analysis and resume tailoring.
        </div>
      )}
      {run && run.status === "FAILED" && <div className="alert alert-error">Last run failed: {run.error}</div>}

      <div className="grid grid-stats mb">
        <Stat label="Jobs discovered" value={c.jobs_discovered} hint={`${c.jobs_discovered_today} today`} />
        <Stat label="Strong matches" value={c.strong_matches} hint={`score 75+ / ${c.strong_matches_today} today`} />
        <Stat label="Recommended" value={c.recommended_applications} hint="APPLY recommendation" />
        <Stat label="Pending review" value={c.pending_review} hint="REVIEW recommendation" />
        <Stat label="Ready to apply" value={c.ready_to_apply} hint="prepared, awaiting you" />
        <Stat label="Applications" value={c.applications_submitted} hint="submitted" />
        <Stat label="Interviews" value={c.interviews} />
      </div>

      <div className="grid grid-2">
        <div>
          <div className="card-title">
            <h2>Top opportunities</h2>
            <Link to="/jobs?only_analyzed=true">All jobs</Link>
          </div>
          {data.top_jobs.length === 0 ? (
            <Empty>
              No analyzed jobs yet. Run a search or open a job and click <b>Analyze</b>.
            </Empty>
          ) : (
            <div className="job-list">
              {data.top_jobs.map((j) => (
                <JobCard key={j.id} job={j} onPrepare={prepare} />
              ))}
            </div>
          )}
        </div>
        <div>
          <div className="card-title">
            <h2>Recent applications</h2>
            <Link to="/applications">Tracker</Link>
          </div>
          {data.recent_applications.length === 0 ? (
            <Empty>No applications yet.</Empty>
          ) : (
            <div className="card">
              <table>
                <thead>
                  <tr><th>Role</th><th>Company</th><th>Status</th><th>Score</th></tr>
                </thead>
                <tbody>
                  {data.recent_applications.map((a) => (
                    <tr key={a.id}>
                      <td><Link to={`/applications/${a.id}`}>{a.role}</Link></td>
                      <td>{a.company}</td>
                      <td><StatusBadge status={a.status} /></td>
                      <td>{a.match_score ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="card mt">
            <h3>Job sources</h3>
            {data.sources.length === 0 ? (
              <p className="muted small">Source registry not available.</p>
            ) : (
              <table>
                <tbody>
                  {data.sources.map((s) => (
                    <tr key={s.name}>
                      <td><b>{s.name}</b><div className="muted small">{s.description}</div></td>
                      <td className="right">
                        {!s.enabled ? <span className="badge">disabled</span> : s.configured ? <span className="badge badge-success">ready</span> : <span className="badge badge-warning" title={s.requires}>needs config</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}
