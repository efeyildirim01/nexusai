from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.ai.llm import ClaudeLanguageModel, LanguageModel
from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.ratelimit import RateLimiter, make_rate_limiter
from app.routers import ai, analytics, auth, datasets, reports, users


def create_app(
    settings: Settings | None = None,
    llm: LanguageModel | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="NexusAI API",
        version="1.0.0",
        description="Multi-tenant business intelligence: uploads, dashboards, safe AI querying.",
    )

    engine = make_engine(str(settings.database_url))
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.readonly_engine = (
        make_engine(str(settings.readonly_database_url)) if settings.readonly_database_url else None
    )
    if llm is None and settings.anthropic_api_key:
        llm = ClaudeLanguageModel(settings.anthropic_api_key, settings.ai_model)
    app.state.llm = llm
    app.state.rate_limiter = rate_limiter or make_rate_limiter(settings.redis_url)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(auth.me_router)
    app.include_router(users.router)
    app.include_router(datasets.router)
    app.include_router(analytics.router)
    app.include_router(ai.router)
    app.include_router(reports.router)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app
