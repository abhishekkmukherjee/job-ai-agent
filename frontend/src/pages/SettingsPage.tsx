import { useEffect, useState } from "react";
import { api } from "../api";
import { ChipInput, ErrorAlert, Loading, formatDateTime, useAsync, useToast } from "../components/common";
import type { RuntimeSettings } from "../types";

export default function SettingsPage() {
  const { data, error, loading, reload } = useAsync(() => api.settings(), []);
  const env = useAsync(() => api.envSummary(), []);
  const runs = useAsync(() => api.searchRuns(8), []);
  const [s, setS] = useState<RuntimeSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const toast = useToast();
  useEffect(() => setS(data), [data]);

  if (loading && !s) return <Loading />;
  if (error) return <ErrorAlert error={error} />;
  if (!s) return null;
  const e = env.data || {};
  const allSources: { name: string; enabled: boolean; configured: boolean; description: string; requires: string }[] = e.sources || [];

  const save = async () => {
    setSaving(true);
    try {
      const saved = await api.updateSettings(s);
      setS(saved);
      toast.show("Settings saved", "success");
      env.reload();
    } catch (er: any) {
      toast.show(er.message, "error");
    } finally {
      setSaving(false);
    }
  };
  const fr = s.filter_rules;
  const setFr = (k: keyof RuntimeSettings["filter_rules"], v: unknown) => setS({ ...s, filter_rules: { ...fr, [k]: v } });
  const sch = s.scheduler;
  const setSch = (k: keyof RuntimeSettings["scheduler"], v: unknown) => setS({ ...s, scheduler: { ...sch, [k]: v } });
  const aa = s.auto_apply;
  const setAa = (k: keyof RuntimeSettings["auto_apply"], v: unknown) => setS({ ...s, auto_apply: { ...aa, [k]: v } });
  const cp = s.career_pages;
  const setCp = (k: keyof RuntimeSettings["career_pages"], v: string[]) => setS({ ...s, career_pages: { ...cp, [k]: v } });
  const enabledSources = s.enabled_sources ?? allSources.filter((x) => x.enabled).map((x) => x.name);
  const toggleSource = (name: string) => {
    const next = enabledSources.includes(name) ? enabledSources.filter((x) => x !== name) : [...enabledSources, name];
    setS({ ...s, enabled_sources: next });
  };

  const test = async (kind: "ai" | "notify") => {
    setTesting(kind);
    try {
      const r = kind === "ai" ? await api.testAI() : await api.testNotification();
      toast.show(JSON.stringify(r).slice(0, 300), "success");
    } catch (er: any) {
      toast.show(er.message, "error");
    } finally {
      setTesting(null);
    }
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <div className="sub">Runtime configuration. API keys live in <code>.env</code> and are never shown here.</div>
        </div>
        <div className="btn-group">
          <button className="btn" onClick={reload}>Reset</button>
          <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? "Saving..." : "Save settings"}</button>
        </div>
      </div>

      <div className="grid grid-2">
        <div>
          <div className="card">
            <h2>AI providers</h2>
            <dl className="kv">
              <dt>Gemini</dt><dd>{e.gemini_configured ? <span className="badge badge-success">configured</span> : <span className="badge badge-warning">GEMINI_API_KEY missing</span>} <span className="muted small">{e.gemini_model}</span></dd>
              <dt>OpenRouter</dt><dd>{e.openrouter_configured ? <span className="badge badge-success">configured</span> : <span className="badge badge-warning">OPENROUTER_API_KEY missing</span>} <span className="muted small">{e.openrouter_model}</span></dd>
              <dt>Groq</dt><dd>{e.groq_configured ? <span className="badge badge-success">configured</span> : <span className="badge">GROQ_API_KEY missing</span>} <span className="muted small">{e.groq_model}</span></dd>
              <dt>Routing</dt>
              <dd>
                {e.ai && e.ai.routes ? (
                  <ul className="reasoning small">
                    {Object.entries(e.ai.routes as Record<string, string[]>).map(([k, v]) => (
                      <li key={k}>{k}: {v.join(" -> ")}</li>
                    ))}
                  </ul>
                ) : "-"}
              </dd>
              <dt>Cache entries</dt><dd>{e.ai_cache_entries ?? 0}</dd>
              <dt>Prompt versions</dt><dd className="small">{e.prompt_versions ? Object.entries(e.prompt_versions).map(([k, v]) => `${k}=${v}`).join(", ") : "-"}</dd>
            </dl>
            <button className="btn btn-sm mt" disabled={!!testing} onClick={() => test("ai")}>{testing === "ai" ? "Testing..." : "Test AI providers"}</button>
          </div>

          <div className="card mt">
            <h2>Scheduler</h2>
            <p className="muted small">Runs the discovery pipeline automatically. Requires the backend process to stay running (or use GitHub Actions - see README).</p>
            <div className="form-row"><label>Enabled</label><div><input type="checkbox" checked={sch.enabled} onChange={(ev) => setSch("enabled", ev.target.checked)} /></div></div>
            <div className="form-row"><label>Cron expression</label><input type="text" value={sch.cron} onChange={(ev) => setSch("cron", ev.target.value)} placeholder="0 8 * * *" /></div>
            <div className="form-row"><label>Timezone</label><input type="text" value={sch.timezone} onChange={(ev) => setSch("timezone", ev.target.value)} /></div>
            <div className="form-row"><label>Analyze with AI</label><div><input type="checkbox" checked={sch.analyze} onChange={(ev) => setSch("analyze", ev.target.checked)} /></div></div>
            <div className="form-row"><label>Send daily report</label><div><input type="checkbox" checked={sch.notify} onChange={(ev) => setSch("notify", ev.target.checked)} /></div></div>
            {e.scheduler && (
              <p className="muted small">
                Status: {e.scheduler.running ? "running" : "stopped"}{e.scheduler.next_run ? `, next run ${formatDateTime(e.scheduler.next_run)}` : ""}
              </p>
            )}
          </div>

          <div className="card mt">
            <h2>Auto-apply</h2>
            <p className="muted small">
              When enabled, the morning run prepares and <b>submits</b> applications for top matches on company career forms. It never submits when a CAPTCHA is present, a required field is unfilled, an answer is flagged for review, or the site is on the blocked list (LinkedIn, Naukri, Indeed...). Every submission and every skipped job is reported to Telegram.
            </p>
            <div className="form-row"><label>Enabled</label><div><input type="checkbox" checked={aa.enabled} onChange={(ev) => setAa("enabled", ev.target.checked)} /></div></div>
            <div className="form-row"><label>Minimum match score</label><input type="number" min={0} max={100} value={aa.min_score} onChange={(ev) => setAa("min_score", Number(ev.target.value))} /></div>
            <div className="form-row"><label>Only APPLY (90+) jobs</label><div><input type="checkbox" checked={aa.require_recommendation_apply} onChange={(ev) => setAa("require_recommendation_apply", ev.target.checked)} /></div></div>
            <div className="form-row"><label>Daily cap</label><input type="number" min={0} max={100} value={aa.daily_cap} onChange={(ev) => setAa("daily_cap", Number(ev.target.value))} /></div>
            <div className="form-row"><label>Apply by email when a posting asks for CVs by mail</label><div><input type="checkbox" checked={aa.email_enabled} onChange={(ev) => setAa("email_enabled", ev.target.checked)} /></div></div>
            <div className="form-row"><label>Max emails per day</label><input type="number" min={0} max={100} value={aa.email_daily_cap} onChange={(ev) => setAa("email_daily_cap", Number(ev.target.value))} /></div>
            <div className="form-row"><label>Seconds between emails</label><input type="number" min={0} max={3600} value={aa.email_min_interval_seconds} onChange={(ev) => setAa("email_min_interval_seconds", Number(ev.target.value))} /></div>
            <div className="form-row"><label>Telegram per application</label><div><input type="checkbox" checked={aa.notify_each} onChange={(ev) => setAa("notify_each", ev.target.checked)} /></div></div>
            <div className="form-row"><label>Blocked domains</label><ChipInput value={aa.blocked_domains} onChange={(v) => setAa("blocked_domains", v)} /></div>
          </div>

          <div className="card mt">
            <h2>Notifications</h2>
            <dl className="kv">
              <dt>Providers</dt><dd>{(e.notification_providers || []).join(", ") || "console"}</dd>
              <dt>Email (SMTP)</dt><dd>{e.smtp_configured ? <span className="badge badge-success">configured</span> : <span className="badge">not configured</span>}</dd>
              <dt>Telegram</dt><dd>{e.telegram_configured ? <span className="badge badge-success">configured</span> : <span className="badge">not configured</span>}</dd>
            </dl>
            <button className="btn btn-sm mt" disabled={!!testing} onClick={() => test("notify")}>{testing === "notify" ? "Sending..." : "Send test notification"}</button>
          </div>

          <div className="card mt">
            <h2>Recent search runs</h2>
            {!runs.data || runs.data.length === 0 ? (
              <p className="muted small">No runs yet.</p>
            ) : (
              <table className="small">
                <thead><tr><th>#</th><th>When</th><th>Status</th><th>Stats</th></tr></thead>
                <tbody>
                  {runs.data.map((r) => (
                    <tr key={r.id}>
                      <td>{r.id}</td>
                      <td>{formatDateTime(r.started_at)}<div className="muted">{r.trigger}</div></td>
                      <td>{r.status}{r.error ? <div className="muted" title={r.error}>error</div> : null}</td>
                      <td><code>{Object.entries(r.stats || {}).filter(([k]) => !["sources", "failures_detail"].includes(k)).map(([k, v]) => `${k}=${v}`).join(" ")}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div>
          <div className="card">
            <h2>Job sources</h2>
            <p className="muted small">Only sources with public APIs are used. Nothing bypasses logins, CAPTCHAs or anti-bot systems.</p>
            <table>
              <tbody>
                {allSources.map((src) => (
                  <tr key={src.name}>
                    <td><input type="checkbox" checked={enabledSources.includes(src.name)} onChange={() => toggleSource(src.name)} /></td>
                    <td><b>{src.name}</b><div className="muted small">{src.description}</div></td>
                    <td className="right">{src.configured ? <span className="badge badge-success">ready</span> : <span className="badge badge-warning" title={src.requires}>{src.requires || "needs config"}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="form-row mt"><label>Extra search queries</label><ChipInput value={s.search_queries} onChange={(v) => setS({ ...s, search_queries: v })} placeholder="e.g. LLM engineer" /></div>
          </div>

          <div className="card mt">
            <h2>Company career pages</h2>
            <p className="muted small">Board slugs for companies whose careers page runs on Greenhouse, Lever or Ashby (the part of the URL after boards.greenhouse.io/, jobs.lever.co/ or jobs.ashbyhq.com/).</p>
            <div className="form-row"><label>Greenhouse</label><ChipInput value={cp.greenhouse} onChange={(v) => setCp("greenhouse", v)} placeholder="e.g. anthropic" /></div>
            <div className="form-row"><label>Lever</label><ChipInput value={cp.lever} onChange={(v) => setCp("lever", v)} placeholder="e.g. mistral" /></div>
            <div className="form-row"><label>Ashby</label><ChipInput value={cp.ashby} onChange={(v) => setCp("ashby", v)} placeholder="e.g. openai" /></div>
          </div>

          <div className="card mt">
            <h2>Rule-based filters</h2>
            <p className="muted small">Cheap deterministic filtering applied before any LLM call.</p>
            <div className="form-row"><label>Reject title keywords</label><ChipInput value={fr.reject_title_keywords} onChange={(v) => setFr("reject_title_keywords", v)} /></div>
            <div className="form-row"><label>Reject description keywords</label><ChipInput value={fr.reject_description_keywords} onChange={(v) => setFr("reject_description_keywords", v)} /></div>
            <div className="form-row"><label>Relevant role keywords</label><ChipInput value={fr.role_keywords} onChange={(v) => setFr("role_keywords", v)} /></div>
            <div className="form-row"><label>Prioritize keywords</label><ChipInput value={fr.prioritize_keywords} onChange={(v) => setFr("prioritize_keywords", v)} /></div>
            <div className="form-row"><label>Reject companies</label><ChipInput value={fr.reject_companies} onChange={(v) => setFr("reject_companies", v)} /></div>
            <div className="form-row"><label>Max years over profile</label><input type="number" value={fr.max_experience_years_over_profile} onChange={(ev) => setFr("max_experience_years_over_profile", Number(ev.target.value))} /></div>
            <div className="form-row"><label>Max job age (days)</label><input type="number" value={fr.max_job_age_days} onChange={(ev) => setFr("max_job_age_days", Number(ev.target.value))} /></div>
            <div className="form-row"><label>Reject remote roles restricted to other regions</label><div><input type="checkbox" checked={fr.reject_remote_outside_regions} onChange={(ev) => setFr("reject_remote_outside_regions", ev.target.checked)} /></div></div>
            <div className="form-row"><label>Treat unknown work mode as onsite</label><div><input type="checkbox" checked={fr.treat_unknown_work_mode_as_onsite} onChange={(ev) => setFr("treat_unknown_work_mode_as_onsite", ev.target.checked)} /></div></div>
            <div className="form-row"><label>Allowed remote regions</label><ChipInput value={fr.allowed_remote_regions} onChange={(v) => setFr("allowed_remote_regions", v)} placeholder="e.g. india, worldwide, apac" /></div>
            <div className="form-row"><label>Reject onsite outside preferred locations</label><div><input type="checkbox" checked={fr.reject_if_onsite_outside_preferred_locations} onChange={(ev) => setFr("reject_if_onsite_outside_preferred_locations", ev.target.checked)} /></div></div>
            <div className="form-row">
              <label>Unknown titles</label>
              <select value={fr.treat_unknown_title_as} onChange={(ev) => setFr("treat_unknown_title_as", ev.target.value)}>
                <option value="unsure">Ask cheap AI model</option>
                <option value="pass">Pass to full analysis</option>
                <option value="reject">Reject</option>
              </select>
            </div>
            <div className="right mb">
              <button
                className="btn btn-sm"
                disabled={!!testing}
                title="Save settings first, then re-run the rules on every job that has not been analyzed yet"
                onClick={async () => {
                  setTesting("refilter");
                  try {
                    const r = await api.refilterJobs();
                    toast.show(`Rules re-applied: ${r.passed_filter} passed, ${r.filtered_out} filtered out`, "success");
                    runs.reload();
                  } catch (er: any) {
                    toast.show(er.message, "error");
                  } finally {
                    setTesting(null);
                  }
                }}
              >
                {testing === "refilter" ? "Re-applying..." : "Re-apply rules to unanalyzed jobs"}
              </button>
            </div>
            <div className="form-row"><label>Min score to show</label><input type="number" value={s.min_score_to_show} onChange={(ev) => setS({ ...s, min_score_to_show: Number(ev.target.value) })} /></div>
          </div>
        </div>
      </div>
      <div className="right mt">
        <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? "Saving..." : "Save settings"}</button>
      </div>
    </div>
  );
}
