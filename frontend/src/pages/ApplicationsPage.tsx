import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Empty, ErrorAlert, Loading, ScoreBadge, StatusBadge, formatDate, useAsync, useToast } from "../components/common";

const STATUSES = ["DISCOVERED", "SHORTLISTED", "APPROVED", "PREPARING", "READY_TO_APPLY", "APPLIED", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"];

export default function ApplicationsPage() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") || "";
  const q = params.get("q") || "";
  const toast = useToast();
  const [busy, setBusy] = useState<number | null>(null);
  const { data, error, loading, reload } = useAsync(() => api.applications({ status: status || undefined, q: q || undefined }), [status, q]);

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    setParams(next);
  };

  const quickStatus = async (id: number, newStatus: string) => {
    setBusy(id);
    try {
      await api.updateApplication(id, { status: newStatus });
      toast.show(`Moved to ${newStatus.replace(/_/g, " ")}`, "success");
      reload();
    } catch (e: any) {
      toast.show(e.message, "error");
    } finally {
      setBusy(null);
    }
  };

  const counts: Record<string, number> = {};
  (data?.items || []).forEach((a) => (counts[a.status] = (counts[a.status] || 0) + 1));

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Application tracker</h1>
          <div className="sub">{data ? `${data.total} applications` : ""}</div>
        </div>
        <button className="btn" onClick={reload}>Refresh</button>
      </div>
      <div className="filters">
        <input type="text" placeholder="Search company / role" value={q} onChange={(e) => set("q", e.target.value)} />
        <select value={status} onChange={(e) => set("status", e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s.replace(/_/g, " ")}{!status && counts[s] ? ` (${counts[s]})` : ""}</option>
          ))}
        </select>
      </div>
      <ErrorAlert error={error} />
      {loading && !data ? (
        <Loading />
      ) : !data || data.items.length === 0 ? (
        <Empty>
          No applications yet. Open a job and click <b>Prepare Application</b>.
        </Empty>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Role</th><th>Company</th><th>Score</th><th>Status</th><th>Applied</th><th>Follow-up</th><th>Resume</th><th></th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((a) => (
                <tr key={a.id}>
                  <td>
                    <Link to={`/applications/${a.id}`}><b>{a.role}</b></Link>
                    <div className="muted small">{a.source}{a.answers.some((x) => x.needs_review) ? " / answers need review" : ""}</div>
                  </td>
                  <td>{a.company}</td>
                  <td><ScoreBadge score={a.match_score} /></td>
                  <td><StatusBadge status={a.status} /></td>
                  <td>{formatDate(a.applied_at)}</td>
                  <td>{formatDate(a.follow_up_date)}</td>
                  <td>{a.has_resume_pdf ? <a href={`/api/applications/${a.id}/resume.pdf`} target="_blank" rel="noreferrer">PDF</a> : <span className="muted">-</span>}</td>
                  <td>
                    <div className="btn-group">
                      {a.status === "READY_TO_APPLY" && (
                        <button className="btn btn-sm btn-success" disabled={busy === a.id} onClick={() => quickStatus(a.id, "APPLIED")}>Mark applied</button>
                      )}
                      {a.status === "APPLIED" && (
                        <button className="btn btn-sm" disabled={busy === a.id} onClick={() => quickStatus(a.id, "INTERVIEW")}>Interview</button>
                      )}
                      <Link className="btn btn-sm" to={`/applications/${a.id}`}>Open</Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
