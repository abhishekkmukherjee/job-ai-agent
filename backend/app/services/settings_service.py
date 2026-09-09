"""Runtime settings persisted in the app_settings table."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AppSetting
from ..schemas.settings import RuntimeSettings, RuntimeSettingsUpdate

SETTINGS_KEY = "runtime"


def get_runtime_settings(db: Session) -> RuntimeSettings:
    row = db.get(AppSetting, SETTINGS_KEY)
    if row is None:
        env = get_settings()
        settings = RuntimeSettings()
        settings.scheduler.enabled = env.scheduler_enabled
        settings.scheduler.cron = env.schedule_cron
        settings.scheduler.timezone = env.schedule_timezone
        db.add(AppSetting(key=SETTINGS_KEY, value=settings.model_dump()))
        db.commit()
        return settings
    try:
        return RuntimeSettings.model_validate(row.value or {})
    except Exception:
        # Corrupt / outdated document -> fall back to defaults but keep what validates.
        return RuntimeSettings()


def update_runtime_settings(db: Session, data: RuntimeSettingsUpdate) -> RuntimeSettings:
    current = get_runtime_settings(db)
    changes = data.model_dump(exclude_unset=True)
    merged = current.model_dump()
    merged.update(changes)
    new_settings = RuntimeSettings.model_validate(merged)
    row = db.get(AppSetting, SETTINGS_KEY)
    if row is None:
        row = AppSetting(key=SETTINGS_KEY, value={})
        db.add(row)
    row.value = new_settings.model_dump()
    db.commit()
    return new_settings


def save_runtime_settings(db: Session, settings: RuntimeSettings) -> None:
    row = db.get(AppSetting, SETTINGS_KEY)
    if row is None:
        row = AppSetting(key=SETTINGS_KEY, value={})
        db.add(row)
    row.value = settings.model_dump()
    db.commit()
