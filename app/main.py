from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import sys

from app.config import settings
from app.routers import documents, query, health, scraper, search

# Configure logging
logger.remove()
logger.add(
    sys.stdout,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    level="INFO"
)

# Create FastAPI app
app = FastAPI(
    title="Bangladesh Banking Knowledge Base API",
    description="AI-powered regulatory intelligence for Bangladesh banking sector",
    version="1.0.0",
    docs_url="/docs"  if settings.APP_ENV == "development" else None,
    redoc_url="/redoc" if settings.APP_ENV == "development" else None,
)

# CORS
origins = settings.ALLOWED_ORIGINS.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all routers
app.include_router(health.router)
app.include_router(documents.router, prefix="/api/v1")
app.include_router(query.router,     prefix="/api/v1")
app.include_router(scraper.router,   prefix="/api/v1")
app.include_router(search.router,    prefix="/api/v1")

@app.get("/")
def root():
    return {
        "message": "Bangladesh Banking Knowledge Base API",
        "version": "1.0.0",
        "docs":    "/docs",
        "status":  "running"
    }

logger.info("BBKB API starting up...")