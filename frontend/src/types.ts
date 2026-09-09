export type RemoteType = "remote" | "hybrid" | "onsite" | "unknown";
export type Recommendation = "APPLY" | "REVIEW" | "LOW_PRIORITY" | "REJECT";
export type PipelineStatus =
  | "NEW"
  | "REJECTED_BY_RULES"
  | "REJECTED_BY_AI_FILTER"
  | "PENDING_ANALYSIS"
  | "ANALYZED"
  | "ANALYSIS_FAILED";
export type UserAction = "NONE" | "SHORTLISTED" | "DISMISSED";
export type ApplicationStatus =
  | "DISCOVERED"
  | "SHORTLISTED"
  | "APPROVED"
  | "PREPARING"
  | "READY_TO_APPLY"
  | "APPLIED"
  | "INTERVIEW"
  | "REJECTED"
  | "OFFER"
  | "WITHDRAWN";

export interface JobAnalysis {
  match_score: number;
  recommendation: Recommendation;
  experience_match: number;
  skill_match: number;
  role_match: number;
  location_match: number;
  salary_match: number;
  reasoning: string[];
  matched_skills: string[];
  missing_requirements: string[];
  red_flags: string[];
  confidence: number;
  summary: string;
}

export interface JobSummary {
  id: number;
  source: string;
  title: string;
  company: string;
  location: string;
  remote_type: RemoteType;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  url: string;
  posted_at: string | null;
  discovered_at: string;
  pipeline_status: PipelineStatus;
  filter_reason: string;
  user_action: UserAction;
  match_score: number | null;
  recommendation: Recommendation | null;
  analysis: JobAnalysis | null;
  is_sample: boolean;
  description_preview: string;
  application_id: number | null;
  application_status: string | null;
}

export interface Job extends JobSummary {
  external_id: string;
  description: string;
  apply_url: string;
  tags: string[];
  filter_details: Record<string, unknown>;
  analyzed_at: string | null;
  analysis_model: string;
  analysis_error: string;
}

export interface JobListResponse {
  items: JobSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface Answer {
  question: string;
  answer: string;
  confidence: number;
  needs_review: boolean;
  field_selector?: string | null;
  edited?: boolean;
  source?: string;
}

export interface TailoredResume {
  headline: string;
  summary: string;
  skills: string[];
  experience: { title: string; company: string; start: string; end: string; bullets: string[] }[];
  projects: { name: string; description: string; technologies: string[] }[];
  education: string[];
  certifications: string[];
  achievements: string[];
  tailoring_notes: string[];
}

export interface FillResult {
  ok: boolean;
  message: string;
  fields_filled: number;
  questions_answered: number;
  resume_uploaded: boolean;
  fields: { label: string; selector: string; value: string; kind: string; status: string }[];
  unmatched_fields: { label: string; selector: string; kind: string }[];
  browser_open: boolean;
  resume: string;
}

export interface Application {
  id: number;
  job_id: number;
  company: string;
  role: string;
  job_url: string;
  source: string;
  match_score: number | null;
  status: ApplicationStatus;
  status_history: { status: string; at: string; note: string }[];
  resume_version: string;
  resume_path: string;
  tailored_resume: TailoredResume | null;
  answers: Answer[];
  cover_note: string;
  fill_result: FillResult | null;
  prepared_at: string | null;
  applied_at: string | null;
  notes: string;
  follow_up_date: string | null;
  interview_dates: string[];
  rejection_reason: string;
  last_error: string;
  created_at: string;
  updated_at: string;
  recommendation: string | null;
  has_resume_pdf: boolean;
}

export interface ExperienceItem {
  title: string;
  company: string;
  start: string;
  end: string;
  location: string;
  bullets: string[];
  technologies: string[];
}
export interface ProjectItem {
  name: string;
  description: string;
  technologies: string[];
  url: string;
  bullets: string[];
}
export interface EducationItem {
  degree: string;
  institution: string;
  year: string;
  details: string;
}

export interface Profile {
  id: number;
  version: number;
  full_name: string;
  email: string;
  phone: string;
  current_location: string;
  preferred_locations: string[];
  linkedin_url: string;
  github_url: string;
  portfolio_url: string;
  years_of_experience: number;
  notice_period: string;
  expected_salary: string;
  work_authorization: string;
  summary: string;
  current_role: string;
  current_company: string;
  experience: ExperienceItem[];
  projects: ProjectItem[];
  skills: string[];
  technologies: string[];
  education: EducationItem[];
  achievements: string[];
  certifications: string[];
  target_roles: string[];
  target_locations: string[];
  remote_preference: "remote" | "hybrid" | "onsite" | "any";
  minimum_salary: number | null;
  salary_currency: string;
  experience_min: number;
  experience_max: number;
  preferred_industries: string[];
  companies_to_avoid: string[];
  keywords_prioritize: string[];
  keywords_reject: string[];
}

export interface DashboardCounts {
  jobs_discovered: number;
  jobs_discovered_today: number;
  strong_matches: number;
  strong_matches_today: number;
  recommended_applications: number;
  applications_submitted: number;
  interviews: number;
  pending_review: number;
  ready_to_apply: number;
}

export interface Dashboard {
  counts: DashboardCounts;
  top_jobs: JobSummary[];
  recent_applications: { id: number; job_id: number; company: string; role: string; status: ApplicationStatus; match_score: number | null; updated_at: string }[];
  last_run: { id: number; status: string; trigger: string; started_at: string; finished_at: string | null; stats: Record<string, unknown>; error: string } | null;
  ai: Record<string, unknown>;
  sources: { name: string; enabled: boolean; configured: boolean; description: string; requires: string }[];
}

export interface FilterRules {
  reject_title_keywords: string[];
  reject_description_keywords: string[];
  role_keywords: string[];
  max_experience_years_over_profile: number;
  min_experience_years_allowed: number;
  reject_if_onsite_outside_preferred_locations: boolean;
  reject_remote_outside_regions: boolean;
  treat_unknown_work_mode_as_onsite: boolean;
  allowed_remote_regions: string[];
  reject_companies: string[];
  prioritize_keywords: string[];
  max_job_age_days: number;
  treat_unknown_title_as: string;
}

export interface RuntimeSettings {
  filter_rules: FilterRules;
  career_pages: { greenhouse: string[]; lever: string[]; ashby: string[] };
  scheduler: { enabled: boolean; cron: string; timezone: string; analyze: boolean; notify: boolean };
  enabled_sources: string[] | null;
  search_queries: string[];
  min_score_to_show: number;
}

export interface SearchRun {
  id: number;
  trigger: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  sources: string[];
  stats: Record<string, unknown>;
  error: string;
}
