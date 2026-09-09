import { Link } from "react-router-dom";
import type { JobSummary } from "../types";
import { PipelineBadge, RecommendationBadge, ScoreBadge, StatusBadge, formatSalary, timeAgo } from "./common";

interface Props {
  job: JobSummary;
  onAnalyze?: (job: JobSummary) => void;
  onTailor?: (job: JobSummary) => void;
  onPrepare?: (job: JobSummary) => void;
  onDismiss?: (job: JobSummary) => void;
  busy?: boolean;
}

export default function JobCard({ job, onAnalyze, onTailor, onPrepare, onDismiss, busy }: Props) {
  const a = job.analysis;
  const salary = formatSalary(job.salary_min, job.salary_max, job.salary_currency);
  return (
    <div className="card job-card">
      <div>
        <div className="title">
          <Link to={`/jobs/${job.id}`}>{job.title}</Link>
        </div>
        <div className="company">
          {job.company || "Unknown company"} {job.location ? ` / ${job.location}` : ""}
        </div>
        <div className="meta">
          <span className="badge">{job.source}</span>
          {job.remote_type !== "unknown" && <span className="badge badge-info">{job.remote_type}</span>}
          {salary && <span>{salary}</span>}
          <span>{job.posted_at ? `posted ${timeAgo(job.posted_at)}` : `found ${timeAgo(job.discovered_at)}`}</span>
          <PipelineBadge status={job.pipeline_status} reason={job.filter_reason} />
          {job.application_status && <StatusBadge status={job.application_status} />}
        </div>
        {a && (
          <>
            {a.matched_skills.length > 0 && (
              <div className="skill-list">
                {a.matched_skills.slice(0, 10).map((s) => (
                  <span className="skill" key={s}>
                    &#10003; {s}
                  </span>
                ))}
                {a.missing_requirements.slice(0, 4).map((s) => (
                  <span className="skill missing" key={`m-${s}`}>
                    missing: {s}
                  </span>
                ))}
              </div>
            )}
            {a.reasoning.length > 0 && (
              <ul className="reasoning small">
                {a.reasoning.slice(0, 3).map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
          </>
        )}
        {!a && job.description_preview && <p className="muted small mt">{job.description_preview}</p>}
        {job.pipeline_status.startsWith("REJECTED") && job.filter_reason && (
          <p className="muted small mt">Filtered: {job.filter_reason}</p>
        )}
      </div>
      <div className="right">
        <ScoreBadge score={job.match_score} />
        <RecommendationBadge value={job.recommendation} />
        <div className="btn-group" style={{ justifyContent: "flex-end" }}>
          {job.url && (
            <a className="btn btn-sm" href={job.url} target="_blank" rel="noreferrer">
              View Job
            </a>
          )}
          {onAnalyze && (
            <button className="btn btn-sm" disabled={busy} onClick={() => onAnalyze(job)}>
              {job.match_score == null ? "Analyze" : "Re-analyze"}
            </button>
          )}
          {onTailor && (
            <button className="btn btn-sm" disabled={busy} onClick={() => onTailor(job)}>
              Tailor Resume
            </button>
          )}
          {onPrepare && (
            <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => onPrepare(job)}>
              {job.application_id ? "Open Application" : "Prepare Application"}
            </button>
          )}
          {onDismiss && job.user_action !== "DISMISSED" && (
            <button className="btn btn-sm" disabled={busy} onClick={() => onDismiss(job)} title="Hide this job">
              Dismiss
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
