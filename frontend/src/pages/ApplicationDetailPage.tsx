import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { ErrorAlert, Loading, ScoreBadge, StatusBadge, formatDateTime, useAsync, useToast } from "../components/common";
import type { Answer, Application, FillResult } from "../types";

const FLOW = ["DISCOVERED", "SHORTLISTED", "APPROVED", "PREPARING", "READY_TO_APPLY", "APPLIED", "INTERVIEW", "OFFER"];
const DEFAULT_QUESTIONS = [
  "Why do you want this role?",
  "Why do you want to work at this company?",
  "Tell us about yourself.",
  "Describe your most relevant experience for this role.",
  "What are your salary expectations?",
  "What is your notice period?",
];

export default function ApplicationDetailPage() {
  const { id } = useParams();
  const appId = Number(id);
  const navigate = useNavigate();
  const toast = useToast();
  const { data: app, error, loading, reload, setData } = useAsync(() => api.application(appId), [appId]);
  const [busy, setBusy] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [notes, setNotes] = useState("");
  const [followUp, setFollowUp] = useState("");
  const [rejection, setRejection] = useState("");
  const [customQ, setCustomQ] = useState("");
  const [fillUrl, setFillUrl] = useState("");
  const [fill, setFill] = useState<FillResult | null>(null);
  const [transitions, setTransitions] = useState<Record<string, string[]>>({});

  useEffect(() => {
    if (!app) return;
    setAnswers(app.answers || []);
    setNotes(app.notes || "");
    setFollowUp(app.follow_up_date ? app.follow_up_date.slice(0, 10) : "");
    setRejection(app.rejection_reason || "");
    setFillUrl(app.job_url || "");
    setFill(app.fill_result);
  }, [app]);
  useEffect(() => {
    api.applicationStatuses().then((r) => setTransitions(r.transitions)).catch(() => undefined);
  }, []);

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

  if (loading && !app) return <Loading />;
  if (error) return <ErrorAlert error={error} />;
  if (!app) return null;

  const allowed = transitions[app.status] || [];
  const resume = app.tailored_resume;
  const needsReview = answers.filter((a) => a.needs_review).length;

  const prepare = (regenerate = false) =>
    run(
      "prepare",
      () => api.prepareApplication(app.id, { questions: DEFAULT_QUESTIONS, regenerate_resume: regenerate }),
      "Application material prepared. Review it below.",
    );

  const saveAnswers = () => run("save", () => api.updateApplication(app.id, { answers }), "Answers saved");
  const saveTracking = () =>
    run(
      "track",
      () =>
        api.updateApplication(app.id, {
          notes,
          follow_up_date: followUp ? new Date(followUp).toISOString() : null,
          rejection_reason: rejection,
        }),
      "Saved",
    );
  const setStatus = (s: string) => run("status", () => api.updateApplication(app.id, { status: s }), `Status: ${s.replace(/_/g, " ")}`);

  const doFill = async () => {
    setBusy("fill");
    try {
      const r = await api.fillApplication(app.id, { url: fillUrl || null });
      setFill(r);
      toast.show(r.ok ? "Form filled. Review the browser window, then submit manually." : r.message, r.ok ? "success" : "error");
      reload();
    } catch (e: any) {
      toast.show(e.message, "error");
    } finally {
      setBusy(null);
    }
  };

  const addQuestion = async () => {
    const q = customQ.trim();
    if (!q) return;
    await run("question", () => api.answerQuestions(app.id, [q]), "Answer generated");
    setCustomQ("");
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <Link to="/applications" className="small">&larr; Applications</Link>
          <h1 style={{ marginTop: 4 }}>
            {app.role} <span className="muted">at</span> {app.company}
          </h1>
          <div className="inline">
            <StatusBadge status={app.status} />
            <ScoreBadge score={app.match_score} />
            <Link to={`/jobs/${app.job_id}`} className="small">job details</Link>
            {app.job_url && (
              <a href={app.job_url} target="_blank" rel="noreferrer" className="small">
                open posting
              </a>
            )}
          </div>
        </div>
        <div className="btn-group">
          <button className="btn btn-primary" disabled={!!busy} onClick={() => prepare(false)}>
            {busy === "prepare" ? "Preparing..." : app.prepared_at ? "Re-generate answers" : "Prepare application material"}
          </button>
          {app.prepared_at && (
            <button className="btn" disabled={!!busy} onClick={() => prepare(true)}>
              Regenerate resume too
            </button>
          )}
        </div>
      </div>

      <div className="card mb">
        <div className="status-steps">
          {FLOW.map((s) => {
            const idx = FLOW.indexOf(app.status);
            const i = FLOW.indexOf(s);
            const cls = s === app.status ? "current" : idx >= 0 && i < idx ? "done" : "";
            return (
              <span key={s} className={`step ${cls}`}>
                {s.replace(/_/g, " ")}
              </span>
            );
          })}
          {["REJECTED", "WITHDRAWN"].includes(app.status) && <span className="step current">{app.status}</span>}
        </div>
        <div className="inline mt">
          <span className="muted small">Move to:</span>
          {allowed.length === 0 && <span className="muted small">no further transitions</span>}
          {allowed.map((s) => (
            <button
              key={s}
              className={`btn btn-sm ${s === "APPLIED" ? "btn-success" : ""}`}
              disabled={!!busy}
              onClick={() => setStatus(s)}
              title={s === "APPLIED" ? "Only mark applied after you submitted the form yourself" : ""}
            >
              {s.replace(/_/g, " ")}
            </button>
          ))}
        </div>
        {app.last_error && <div className="alert alert-error mt">{app.last_error}</div>}
      </div>

      <div className="grid grid-2">
        <div>
          <div className="card">
            <div className="card-title">
              <h2>Tailored resume</h2>
              {app.has_resume_pdf && (
                <a className="btn btn-sm" href={`/api/applications/${app.id}/resume.pdf`} target="_blank" rel="noreferrer">
                  Download PDF
                </a>
              )}
            </div>
            {!resume ? (
              <p className="muted">
                No tailored resume yet. Click <b>Prepare application material</b>. The resume is generated only from facts in your profile.
              </p>
            ) : (
              <div>
                <h3>{resume.headline}</h3>
                <p>{resume.summary}</p>
                <div className="skill-list mb">
                  {resume.skills.map((s) => (
                    <span className="badge badge-primary" key={s}>
                      {s}
                    </span>
                  ))}
                </div>
                {resume.experience.map((e, i) => (
                  <div key={i} className="mb">
                    <b>{e.title}</b> - {e.company} <span className="muted small">{e.start} - {e.end}</span>
                    <ul className="reasoning">
                      {e.bullets.map((b, j) => (
                        <li key={j}>{b}</li>
                      ))}
                    </ul>
                  </div>
                ))}
                {resume.projects.length > 0 && (
                  <>
                    <h3>Projects</h3>
                    {resume.projects.map((p, i) => (
                      <div key={i} className="mb">
                        <b>{p.name}</b> - {p.description}
                        <div className="muted small">{p.technologies.join(", ")}</div>
                      </div>
                    ))}
                  </>
                )}
                {resume.education.length > 0 && (
                  <>
                    <h3>Education</h3>
                    <ul className="reasoning">{resume.education.map((e, i) => <li key={i}>{e}</li>)}</ul>
                  </>
                )}
                {resume.tailoring_notes.length > 0 && (
                  <div className="alert alert-info mt small">
                    <b>What was tailored:</b>
                    <ul className="reasoning">{resume.tailoring_notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
                  </div>
                )}
                <p className="muted small">Version {app.resume_version} / generated {formatDateTime(app.prepared_at)}</p>
              </div>
            )}
          </div>

          <div className="card mt">
            <h2>Tracking</h2>
            <div className="form-row">
              <label>Notes</label>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
            </div>
            <div className="form-row">
              <label>Follow-up date</label>
              <input type="date" value={followUp} onChange={(e) => setFollowUp(e.target.value)} />
            </div>
            <div className="form-row">
              <label>Rejection reason</label>
              <input type="text" value={rejection} onChange={(e) => setRejection(e.target.value)} />
            </div>
            <div className="form-row">
              <label>Applied at</label>
              <div style={{ paddingTop: 7 }}>{formatDateTime(app.applied_at)}</div>
            </div>
            <div className="right">
              <button className="btn" disabled={!!busy} onClick={saveTracking}>
                Save
              </button>
            </div>
            <h3 className="mt">History</h3>
            <ul className="reasoning small">
              {(app.status_history || []).map((h, i) => (
                <li key={i}>
                  {formatDateTime(h.at)} - {h.status.replace(/_/g, " ")} {h.note ? `(${h.note})` : ""}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div>
          <div className="card">
            <div className="card-title">
              <h2>Application answers</h2>
              {needsReview > 0 && <span className="badge badge-warning">{needsReview} need review</span>}
            </div>
            {answers.length === 0 && (
              <p className="muted">
                No answers yet. Prepare the application to generate answers for common questions, or add a specific question below.
              </p>
            )}
            {answers.map((a, i) => (
              <div className="answer" key={i}>
                <div className="q">
                  {a.question}{" "}
                  {a.needs_review ? (
                    <span className="badge badge-warning">needs review</span>
                  ) : (
                    <span className="badge badge-success">confidence {(a.confidence * 100).toFixed(0)}%</span>
                  )}
                </div>
                <textarea
                  value={a.answer}
                  onChange={(e) => setAnswers(answers.map((x, j) => (j === i ? { ...x, answer: e.target.value, needs_review: false } : x)))}
                />
                <div className="right">
                  <button className="btn btn-sm" onClick={() => setAnswers(answers.filter((_, j) => j !== i))}>
                    remove
                  </button>
                </div>
              </div>
            ))}
            <div className="inline mt">
              <input
                type="text"
                placeholder="Add a question from the application form..."
                value={customQ}
                onChange={(e) => setCustomQ(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addQuestion()}
              />
              <button className="btn" disabled={!!busy || !customQ.trim()} onClick={addQuestion}>
                Generate answer
              </button>
            </div>
            {answers.length > 0 && (
              <div className="right mt">
                <button className="btn btn-primary" disabled={!!busy} onClick={saveAnswers}>
                  Save answers
                </button>
              </div>
            )}
          </div>

          <div className="card mt">
            <h2>Fill application form</h2>
            <p className="muted small">
              Opens a browser, maps the form fields to your profile, fills them, uploads the tailored resume and answers text questions.
              It <b>stops before submission</b> - you review and click submit yourself.
            </p>
            <div className="form-row">
              <label>Application URL</label>
              <input type="url" value={fillUrl} onChange={(e) => setFillUrl(e.target.value)} placeholder="https://..." />
            </div>
            <div className="kv mb">
              <dt>Resume</dt>
              <dd>{app.has_resume_pdf ? app.resume_path.split(/[\\/]/).pop() : "not generated yet"}</dd>
              <dt>Answers ready</dt>
              <dd>{answers.length}</dd>
            </div>
            <div className="btn-group">
              <button className="btn btn-primary" disabled={!!busy || !fillUrl} onClick={doFill}>
                {busy === "fill" ? "Filling..." : "Fill Application"}
              </button>
              <button
                className="btn"
                disabled={!!busy || !fillUrl}
                title="For LinkedIn, Naukri, Indeed, YC: opens your own logged-in browser, pre-fills the form, you press submit"
                onClick={async () => {
                  setBusy("assist");
                  try {
                    const r = await api.assistApplication(app.id, { url: fillUrl || null });
                    setFill(r);
                    toast.show(r.ok ? "Browser opened and pre-filled. Review it there and press submit yourself." : r.message, r.ok ? "success" : "error");
                    reload();
                  } catch (e: any) {
                    toast.show(e.message, "error");
                  } finally {
                    setBusy(null);
                  }
                }}
              >
                {busy === "assist" ? "Opening..." : "Assist in my browser"}
              </button>
              {fillUrl && (
                <a className="btn" href={fillUrl} target="_blank" rel="noreferrer">
                  Open Application
                </a>
              )}
              <button className="btn" disabled={!!busy} onClick={() => run("close", () => api.closeBrowser(app.id), "Browser closed")}>
                Close browser
              </button>
            </div>
            {fill && (
              <div className={`alert mt ${fill.ok ? "alert-success" : "alert-error"}`}>
                <b>{fill.submitted ? "Application SUBMITTED." : fill.ok ? "Application filled successfully." : "Fill failed."}</b> {fill.message}
                {fill.ok && !fill.submitted && (
                  <div className="mt">
                    <b>DO NOT SUBMIT automatically.</b> Fields filled: {fill.fields_filled} / Questions answered: {fill.questions_answered} / Resume uploaded:{" "}
                    {fill.resume_uploaded ? "yes" : "no"}
                    {fill.browser_open ? " / Browser window is open for your review." : ""}
                  </div>
                )}
                {fill.fields.length > 0 && (
                  <details className="mt">
                    <summary>Field mapping ({fill.fields.length})</summary>
                    <table className="small">
                      <tbody>
                        {fill.fields.map((f, i) => (
                          <tr key={i}>
                            <td>{f.label}</td>
                            <td className="muted">{f.kind}</td>
                            <td>{f.value.length > 60 ? f.value.slice(0, 60) + "..." : f.value}</td>
                            <td>{f.status}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </details>
                )}
                {fill.unmatched_fields.length > 0 && (
                  <details className="mt">
                    <summary>Unmatched fields ({fill.unmatched_fields.length}) - fill these manually</summary>
                    <ul className="reasoning small">
                      {fill.unmatched_fields.map((f, i) => (
                        <li key={i}>
                          {f.label || f.selector} <span className="muted">({f.kind})</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
                {fill.ok && app.status !== "APPLIED" && (
                  <div className="mt">
                    <button className="btn btn-success btn-sm" disabled={!!busy} onClick={() => setStatus("APPLIED")}>
                      I submitted it manually - mark as APPLIED
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="mt right">
        <button
          className="btn btn-danger btn-sm"
          disabled={!!busy}
          onClick={async () => {
            if (!confirm("Delete this application record?")) return;
            try {
              await api.deleteApplication(app.id);
              navigate("/applications");
            } catch (e: any) {
              toast.show(e.message, "error");
            }
          }}
        >
          Delete application
        </button>
      </div>
    </div>
  );
}
