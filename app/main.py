from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers import analysis, health, refresh, watchlist, wiki
from app.jobs import scheduler as job_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    job_scheduler.start()
    yield
    job_scheduler.shutdown()


app = FastAPI(title="Personal Investment Research App", lifespan=lifespan)

app.include_router(health.router)
app.include_router(wiki.router)
app.include_router(watchlist.router)
app.include_router(refresh.router)
app.include_router(analysis.router)
