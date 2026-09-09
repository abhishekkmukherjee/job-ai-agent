import { useEffect, useState } from "react";
import { api } from "../api";
import { ChipInput, ErrorAlert, Loading, useAsync, useToast } from "../components/common";
import type { EducationItem, ExperienceItem, Profile, ProjectItem } from "../types";

export default function ProfilePage() {
  const { data, error, loading, reload } = useAsync(() => api.profile(), []);
  const [p, setP] = useState<Profile | null>(null);
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  useEffect(() => setP(data), [data]);

  if (loading && !p) return <Loading />;
  if (error) return <ErrorAlert error={error} />;
  if (!p) return null;

  const upd = <K extends keyof Profile>(k: K, v: Profile[K]) => setP({ ...p, [k]: v });
  const save = async () => {
    setSaving(true);
    try {
      const { id, version, ...body } = p;
      const saved = await api.updateProfile(body);
      setP(saved);
      toast.show(`Profile saved (version ${saved.version}). Cached AI results will be recomputed.`, "success");
    } catch (e: any) {
      toast.show(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const text = (label: string, key: keyof Profile, type = "text") => (
    <div className="form-row">
      <label>{label}</label>
      <input type={type} value={(p[key] as string | number) ?? ""} onChange={(e) => upd(key, (type === "number" ? Number(e.target.value) : e.target.value) as never)} />
    </div>
  );
  const chips = (label: string, key: keyof Profile, placeholder?: string) => (
    <div className="form-row">
      <label>{label}</label>
      <ChipInput value={(p[key] as string[]) || []} onChange={(v) => upd(key, v as never)} placeholder={placeholder} />
    </div>
  );

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Profile</h1>
          <div className="sub">
            Master profile, version {p.version}. Everything the AI writes about you must come from here - it never invents experience.
          </div>
        </div>
        <div className="btn-group">
          <button className="btn" onClick={reload}>Reset</button>
          <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? "Saving..." : "Save profile"}</button>
        </div>
      </div>

      <div className="grid grid-2">
        <div>
          <div className="card">
            <h2>Personal information</h2>
            {text("Full name", "full_name")}
            {text("Email", "email", "email")}
            {text("Phone", "phone")}
            {text("Current location", "current_location")}
            {chips("Preferred locations", "preferred_locations")}
            {text("LinkedIn", "linkedin_url", "url")}
            {text("GitHub", "github_url", "url")}
            {text("Portfolio", "portfolio_url", "url")}
            {text("Years of experience", "years_of_experience", "number")}
            {text("Notice period", "notice_period")}
            {text("Expected salary", "expected_salary")}
            {text("Work authorization", "work_authorization")}
            <div className="form-row">
              <label>Summary</label>
              <textarea value={p.summary} onChange={(e) => upd("summary", e.target.value)} />
            </div>
          </div>

          <div className="card mt">
            <h2>Job preferences</h2>
            {chips("Target roles", "target_roles")}
            {chips("Target locations", "target_locations")}
            <div className="form-row">
              <label>Work mode</label>
              <select value={p.remote_preference} onChange={(e) => upd("remote_preference", e.target.value as Profile["remote_preference"])}>
                <option value="any">Any</option>
                <option value="remote">Remote</option>
                <option value="hybrid">Hybrid</option>
                <option value="onsite">Onsite</option>
              </select>
            </div>
            <div className="form-row">
              <label>Minimum salary</label>
              <div className="inline">
                <input type="number" value={p.minimum_salary ?? ""} onChange={(e) => upd("minimum_salary", e.target.value ? Number(e.target.value) : null)} style={{ width: 160 }} />
                <input type="text" value={p.salary_currency} onChange={(e) => upd("salary_currency", e.target.value)} style={{ width: 80 }} />
              </div>
            </div>
            <div className="form-row">
              <label>Experience range</label>
              <div className="inline">
                <input type="number" value={p.experience_min} onChange={(e) => upd("experience_min", Number(e.target.value))} style={{ width: 80 }} /> to
                <input type="number" value={p.experience_max} onChange={(e) => upd("experience_max", Number(e.target.value))} style={{ width: 80 }} /> years
              </div>
            </div>
            {chips("Preferred industries", "preferred_industries")}
            {chips("Companies to avoid", "companies_to_avoid")}
            {chips("Keywords to prioritize", "keywords_prioritize")}
            {chips("Keywords to reject", "keywords_reject")}
          </div>
        </div>

        <div>
          <div className="card">
            <h2>Professional profile</h2>
            {text("Current role", "current_role")}
            {text("Current company", "current_company")}
            {chips("Skills", "skills")}
            {chips("Technologies", "technologies")}
            {chips("Achievements", "achievements", "one achievement, press Enter")}
            {chips("Certifications", "certifications")}
          </div>

          <div className="card mt">
            <div className="card-title">
              <h2>Experience</h2>
              <button className="btn btn-sm" onClick={() => upd("experience", [...p.experience, { title: "", company: "", start: "", end: "", location: "", bullets: [], technologies: [] }])}>+ Add</button>
            </div>
            {p.experience.map((e, i) => (
              <ExperienceEditor key={i} item={e} onChange={(v) => upd("experience", p.experience.map((x, j) => (j === i ? v : x)))} onRemove={() => upd("experience", p.experience.filter((_, j) => j !== i))} />
            ))}
          </div>

          <div className="card mt">
            <div className="card-title">
              <h2>Projects</h2>
              <button className="btn btn-sm" onClick={() => upd("projects", [...p.projects, { name: "", description: "", technologies: [], url: "", bullets: [] }])}>+ Add</button>
            </div>
            {p.projects.map((pr, i) => (
              <ProjectEditor key={i} item={pr} onChange={(v) => upd("projects", p.projects.map((x, j) => (j === i ? v : x)))} onRemove={() => upd("projects", p.projects.filter((_, j) => j !== i))} />
            ))}
          </div>

          <div className="card mt">
            <div className="card-title">
              <h2>Education</h2>
              <button className="btn btn-sm" onClick={() => upd("education", [...p.education, { degree: "", institution: "", year: "", details: "" }])}>+ Add</button>
            </div>
            {p.education.map((ed, i) => (
              <EducationEditor key={i} item={ed} onChange={(v) => upd("education", p.education.map((x, j) => (j === i ? v : x)))} onRemove={() => upd("education", p.education.filter((_, j) => j !== i))} />
            ))}
          </div>
        </div>
      </div>
      <div className="right mt">
        <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? "Saving..." : "Save profile"}</button>
      </div>
    </div>
  );
}

function ExperienceEditor({ item, onChange, onRemove }: { item: ExperienceItem; onChange: (v: ExperienceItem) => void; onRemove: () => void }) {
  const u = (k: keyof ExperienceItem, v: unknown) => onChange({ ...item, [k]: v });
  return (
    <div className="answer">
      <div className="grid grid-2">
        <input type="text" placeholder="Title" value={item.title} onChange={(e) => u("title", e.target.value)} />
        <input type="text" placeholder="Company" value={item.company} onChange={(e) => u("company", e.target.value)} />
        <input type="text" placeholder="Start (e.g. Jan 2023)" value={item.start} onChange={(e) => u("start", e.target.value)} />
        <input type="text" placeholder="End (or Present)" value={item.end} onChange={(e) => u("end", e.target.value)} />
      </div>
      <div className="mt">
        <label className="muted small">Bullet points (one per line)</label>
        <textarea value={item.bullets.join("\n")} onChange={(e) => u("bullets", e.target.value.split("\n"))} onBlur={(e) => u("bullets", e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))} />
      </div>
      <div className="mt">
        <label className="muted small">Technologies</label>
        <ChipInput value={item.technologies} onChange={(v) => u("technologies", v)} />
      </div>
      <div className="right mt"><button className="btn btn-sm btn-danger" onClick={onRemove}>Remove</button></div>
    </div>
  );
}

function ProjectEditor({ item, onChange, onRemove }: { item: ProjectItem; onChange: (v: ProjectItem) => void; onRemove: () => void }) {
  const u = (k: keyof ProjectItem, v: unknown) => onChange({ ...item, [k]: v });
  return (
    <div className="answer">
      <div className="grid grid-2">
        <input type="text" placeholder="Project name" value={item.name} onChange={(e) => u("name", e.target.value)} />
        <input type="url" placeholder="URL" value={item.url} onChange={(e) => u("url", e.target.value)} />
      </div>
      <textarea className="mt" placeholder="Description" value={item.description} onChange={(e) => u("description", e.target.value)} />
      <div className="mt">
        <label className="muted small">Bullet points (one per line)</label>
        <textarea value={item.bullets.join("\n")} onChange={(e) => u("bullets", e.target.value.split("\n"))} onBlur={(e) => u("bullets", e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))} />
      </div>
      <div className="mt">
        <label className="muted small">Technologies</label>
        <ChipInput value={item.technologies} onChange={(v) => u("technologies", v)} />
      </div>
      <div className="right mt"><button className="btn btn-sm btn-danger" onClick={onRemove}>Remove</button></div>
    </div>
  );
}

function EducationEditor({ item, onChange, onRemove }: { item: EducationItem; onChange: (v: EducationItem) => void; onRemove: () => void }) {
  const u = (k: keyof EducationItem, v: unknown) => onChange({ ...item, [k]: v });
  return (
    <div className="answer">
      <div className="grid grid-2">
        <input type="text" placeholder="Degree" value={item.degree} onChange={(e) => u("degree", e.target.value)} />
        <input type="text" placeholder="Institution" value={item.institution} onChange={(e) => u("institution", e.target.value)} />
        <input type="text" placeholder="Year" value={item.year} onChange={(e) => u("year", e.target.value)} />
        <input type="text" placeholder="Details" value={item.details} onChange={(e) => u("details", e.target.value)} />
      </div>
      <div className="right mt"><button className="btn btn-sm btn-danger" onClick={onRemove}>Remove</button></div>
    </div>
  );
}
