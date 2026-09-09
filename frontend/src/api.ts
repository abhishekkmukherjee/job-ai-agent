import type {
  Application,
  Dashboard,
  Job,
  JobListResponse,
  Profile,
  RuntimeSettings,
  SearchRun,
  FillResult,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  dashboard: () => request<Dashboard>("/api/dashboard"),
  jobs: (params: Record<string, string | number | boolean | null | undefined>) =>
    request<JobListResponse>(`/api/jobs${qs(params)}`),
  jobsMeta: () => request<{ sources: string[]; companies: string[] }>("/api/jobs/meta"),
  job: (id: number) => request<Job>(`/api/jobs/${id}`),
  updateJob: (id: number, body: { user_action: string }) =>
    request<Job>(`/api/jobs/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  analyzeJob: (id: number, force = false) =>
    request<Job>(`/api/jobs/${id}/analyze${qs({ force })}`, { method: "POST" }),
  tailorResume: (id: number, force = false) =>
    request<{ application_id: number; resume: unknown; resume_path: string }>(
      `/api/jobs/${id}/tailor-resume${qs({ force })}`,
      { method: "POST" },
    ),
  searchJobs: (body: { sources?: string[] | null; analyze?: boolean; notify?: boolean; max_per_source?: number | null }) =>
    request<{ run_id: number; status: string; message: string }>("/api/jobs/search", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  refilterJobs: () => request<Record<string, number>>("/api/jobs/refilter", { method: "POST" }),
  searchRuns: (limit = 10) => request<SearchRun[]>(`/api/search-runs${qs({ limit })}`),
  searchRun: (id: number) => request<SearchRun>(`/api/search-runs/${id}`),

  applications: (params: Record<string, string | undefined> = {}) =>
    request<{ items: Application[]; total: number }>(`/api/applications${qs(params)}`),
  application: (id: number) => request<Application>(`/api/applications/${id}`),
  createApplication: (job_id: number, status = "SHORTLISTED") =>
    request<Application>("/api/applications", { method: "POST", body: JSON.stringify({ job_id, status }) }),
  updateApplication: (id: number, body: Record<string, unknown>) =>
    request<Application>(`/api/applications/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteApplication: (id: number) => request<void>(`/api/applications/${id}`, { method: "DELETE" }),
  prepareApplication: (id: number, body: { questions?: string[]; regenerate_resume?: boolean; regenerate_answers?: boolean }) =>
    request<Application>(`/api/applications/${id}/prepare`, { method: "POST", body: JSON.stringify(body) }),
  answerQuestions: (id: number, questions: string[]) =>
    request<Application>(`/api/applications/${id}/answer-questions`, {
      method: "POST",
      body: JSON.stringify({ questions }),
    }),
  fillApplication: (id: number, body: { url?: string | null; headless?: boolean | null }) =>
    request<FillResult>(`/api/applications/${id}/fill`, { method: "POST", body: JSON.stringify(body) }),
  assistApplication: (id: number, body: { url?: string | null }) =>
    request<FillResult>(`/api/applications/${id}/assist`, { method: "POST", body: JSON.stringify(body) }),
  closeBrowser: (id: number) => request<{ closed: boolean }>(`/api/applications/${id}/close-browser`, { method: "POST" }),
  applicationStatuses: () => request<{ statuses: string[]; transitions: Record<string, string[]> }>("/api/applications/statuses"),

  profile: () => request<Profile>("/api/profile"),
  updateProfile: (body: Partial<Profile>) => request<Profile>("/api/profile", { method: "PATCH", body: JSON.stringify(body) }),

  settings: () => request<RuntimeSettings>("/api/settings"),
  updateSettings: (body: Partial<RuntimeSettings>) =>
    request<RuntimeSettings>("/api/settings", { method: "PATCH", body: JSON.stringify(body) }),
  envSummary: () => request<Record<string, any>>("/api/settings/env"),
  testNotification: () => request<{ results: Record<string, unknown> }>("/api/settings/notifications/test", { method: "POST" }),
  testAI: () => request<Record<string, unknown>>("/api/settings/ai/test", { method: "POST" }),
};
