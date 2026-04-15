import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from app.config import settings

# ── Logging ──────────────────────────────────────────────────
logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    level="INFO"
)

# ── App ──────────────────────────────────────────────────────
app = FastAPI(
    title="Bangladesh Banking Knowledge Base API",
    description="AI-powered regulatory intelligence for Bangladesh banking sector",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ─────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# ── Routers ───────────────────────────────────────────────────
from app.routers import documents, query, health, scraper, search, admin

app.include_router(health.router)
app.include_router(documents.router, prefix="/api/v1")
app.include_router(query.router,     prefix="/api/v1")
app.include_router(scraper.router,   prefix="/api/v1")
app.include_router(search.router,    prefix="/api/v1")
app.include_router(admin.router)

# ── Root ──────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "message": "Bangladesh Banking Knowledge Base API",
        "version": "1.0.0",
        "status":  "running",
        "docs":    "/docs",
    }

logger.info("BBKB API starting up...")