from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import ChatMessage
from app.db.session import get_db
from app.providers.base import ProviderError
from app.services import chat_service

router = APIRouter(tags=["chat"])


class ChatMessageInput(BaseModel):
    message: str


def _serialize(message: ChatMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role.value,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
    }


@router.get("/chat/messages")
def list_messages(db: Session = Depends(get_db)):
    return [_serialize(m) for m in chat_service.list_messages(db)]


@router.post("/chat")
def send_message(body: ChatMessageInput, db: Session = Depends(get_db)):
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="message must not be empty")

    try:
        reply = chat_service.send_message(db, body.message.strip())
    except chat_service.NoTrackedCompaniesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except chat_service.QuotaExhaustedError:
        raise HTTPException(status_code=429, detail="AI quota reached, try again later.")
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _serialize(reply)
