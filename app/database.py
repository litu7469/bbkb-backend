from supabase import create_client, Client
from app.config import settings

def get_supabase() -> Client:
    """Returns a Supabase client using the service role key (for backend use)."""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)

def get_supabase_anon() -> Client:
    """Returns a Supabase client using the anon key (for public reads)."""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)

# Single shared instance
supabase: Client = get_supabase()