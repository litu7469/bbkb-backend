from fastapi import APIRouter, BackgroundTasks, HTTPException
from app.database import supabase

router = APIRouter(prefix="/admin/scraper", tags=["Scraper"])

# Simple flag to prevent running two scrapers at once
_scraper_running = False

@router.post("/run")
def trigger_scraper(background_tasks: BackgroundTasks):
    """
    Manually trigger the Bangladesh Bank scraper.
    Runs in background — only one instance allowed at a time.
    """
    global _scraper_running

    if _scraper_running:
        raise HTTPException(
            status_code=409,
            detail="Scraper is already running. Check /admin/scraper/status for progress."
        )

    def run_with_flag():
        global _scraper_running
        _scraper_running = True
        try:
            from scrapers.bb_scraper import run_bb_scraper
            run_bb_scraper()
        finally:
            _scraper_running = False

    background_tasks.add_task(run_with_flag)

    return {
        "message": "Scraper started in background.",
        "note":    "Check /admin/scraper/status to see progress."
    }

@router.get("/jobs")
def get_scraper_jobs():
    """See history of all scraper runs."""
    result = (
        supabase.table("scraper_jobs")
        .select("*")
        .order("started_at", desc=True)
        .limit(20)
        .execute()
    )
    return {"jobs": result.data}

@router.get("/status")
def scraper_status():
    """Get the status of the most recent scraper run."""
    result = (
        supabase.table("scraper_jobs")
        .select("*")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data:
        return {"status": "never_run", "message": "Scraper has not been run yet."}

    job = result.data[0]
    job["currently_running"] = _scraper_running
    return job