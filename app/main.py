from fastapi import FastAPI

from app.api.routers import health, wiki

app = FastAPI(title="Personal Investment Research App")

app.include_router(health.router)
app.include_router(wiki.router)
