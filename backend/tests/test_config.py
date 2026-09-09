from app.config import ROOT_DIR, Settings


def test_relative_sqlite_path_resolves_against_project_root():
    s = Settings(database_url="sqlite:///./data/test_relative.db")
    expected = (ROOT_DIR / "data" / "test_relative.db").resolve().as_posix()
    assert s.database_url == "sqlite:///" + expected


def test_absolute_and_memory_sqlite_paths_untouched(tmp_path):
    absolute = (tmp_path / "x.db").as_posix()
    assert Settings(database_url=f"sqlite:///{absolute}").database_url == f"sqlite:///{absolute}"
    assert Settings(database_url="sqlite:///:memory:").database_url == "sqlite:///:memory:"
    assert Settings(database_url="postgresql+psycopg://u:p@h/db").database_url.startswith("postgresql")


def test_env_example_lists_every_documented_key():
    text = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
    for key in ["GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "DATABASE_URL", "JOB_ANALYSIS_PROMPT_VERSION"]:
        assert key in text
