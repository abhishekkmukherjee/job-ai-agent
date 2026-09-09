from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..schemas.profile import ProfileRead, ProfileUpdate
from ..services import profile_service
from .deps import get_db

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=ProfileRead)
def read_profile(db: Session = Depends(get_db)) -> ProfileRead:
    return ProfileRead.model_validate(profile_service.get_profile(db))


@router.patch("", response_model=ProfileRead)
def patch_profile(data: ProfileUpdate, db: Session = Depends(get_db)) -> ProfileRead:
    return ProfileRead.model_validate(profile_service.update_profile(db, data))
