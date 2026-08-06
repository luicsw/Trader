from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers import (
    analysis,
    chat,
    forecast,
    health,
    holdings,
    outcomes,
    portfolio,
    price_history,
    refresh,
    search,
    status,
    tickers,
    watchlist,
    wiki,
)
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
app.include_router(holdings.router)
app.include_router(portfolio.router)
app.include_router(price_history.router)
app.include_router(chat.router)
app.include_router(refresh.router)
app.include_router(analysis.router)
app.include_router(forecast.router)
app.include_router(outcomes.router)
app.include_router(search.router)
app.include_router(tickers.router)
app.include_router(status.router)
