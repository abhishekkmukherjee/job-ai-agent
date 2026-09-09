# Prompts

All LLM prompts live here as plain text with `{{placeholder}}` variables.

| File | Task | Version env var |
|------|------|-----------------|
| `job_analysis.txt` | Structured job/profile match scoring | `JOB_ANALYSIS_PROMPT_VERSION` |
| `job_filtering.txt` | Cheap relevance classification before full analysis | `JOB_FILTERING_PROMPT_VERSION` |
| `resume_tailoring.txt` | Resume tailored from master profile facts only | `RESUME_TAILORING_PROMPT_VERSION` |
| `application_questions.txt` | Grounded answers to application questions | `APPLICATION_QUESTIONS_PROMPT_VERSION` |

To iterate on a prompt without losing the old one, save the new version as
`job_analysis.v2.txt` and set `JOB_ANALYSIS_PROMPT_VERSION=2`.  The version is part
of the AI cache key, so results are recomputed only for the changed task.
