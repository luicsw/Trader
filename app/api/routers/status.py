from fastapi import APIRouter

from app.config import settings
from app.providers import groq_client

router = APIRouter(tags=["status"])


@router.get("/status")
def status():
    """Capability flags the frontend uses to decide what to offer (spec.md FR-33a). `features`
    is derived purely from key presence, so a dormant provider becomes a *disabled* action with
    an honest tooltip rather than a button that 503s -- and the moment a key is dropped into the
    environment, this flips to true with no code change (that's the activation acceptance test).
    """
    return {
        "features": {
            "forecast": groq_client.is_available(settings.groq_api_key),
        }
    }
