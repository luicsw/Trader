from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import provider_orchestrator

router = APIRouter(tags=["search"])


@router.get("/companies/search")
def search_companies(q: str, db: Session = Depends(get_db)):
    if not q or not q.strip():
        return []
    return provider_orchestrator.search_symbols_best_effort(db, q.strip())
