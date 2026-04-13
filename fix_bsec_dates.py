import re
from datetime import datetime, date
from loguru import logger
from app.database import supabase

TODAY = str(date.today())

MONTH_MAP = {
    'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
    'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
    'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
    'january': '01', 'february': '02', 'march': '03',
    'april': '04', 'june': '06', 'july': '07',
    'august': '08', 'september': '09', 'october': '10',
    'november': '11', 'december': '12',
}


def valid(y, mo, d):
    try:
        datetime(int(y), int(mo), int(d))
        return 1990 <= int(y) <= 2030
    except ValueError:
        return False


def fmt(y, mo, d):
    return f"{y}-{str(mo).zfill(2)}-{str(d).zfill(2)}"


def get_date(url):
    if not url:
        return ""
    f = url.split('/')[-1].replace('.pdf', '').replace('.PDF', '')

    # Pattern 1: DD.MM.YYYY
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(20\d{2})', f)
    if m:
        d, mo, y = m.groups()
        if valid(y, mo, d):
            return fmt(y, mo, d)

    # Pattern 2: _DD_MM_YYYY
    m = re.search(r'_(\d{1,2})_(\d{1,2})_(20\d{2})', f)
    if m:
        d, mo, y = m.groups()
        if valid(y, mo, d):
            return fmt(y, mo, d)

    # Pattern 3: _DD_MM_YY (2-digit year at end)
    m = re.search(r'_(\d{1,2})_(\d{1,2})_(\d{2})$', f)
    if m:
        d, mo, y = m.groups()
        y = '20' + y
        if valid(y, mo, d):
            return fmt(y, mo, d)

    # Pattern 4: DD.MM.YY (dots, 2-digit year)
    # e.g. 20.12.11, 16.4.12, 09.01.11
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{2})(?:[^0-9]|$)', f)
    if m:
        d, mo, y = m.groups()
        y = '20' + y
        if valid(y, mo, d):
            return fmt(y, mo, d)

    # Pattern 5: DDMmmYY (3-letter month, no separator)
    # e.g. 11mar10, 27may09, 17Nov09, 1Mar10
    m = re.search(
        r'(\d{1,2})(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(\d{2})(?:[^a-z]|$)',
        f, re.IGNORECASE
    )
    if m:
        d, mon, y = m.groups()
        mo = MONTH_MAP[mon.lower()]
        y  = '20' + y
        if valid(y, mo, d):
            return fmt(y, mo, d)

    # Pattern 6: DDFullMonthYY (full month name, no separator)
    # e.g. 30June10, 31May10, 14July10
    m = re.search(
        r'(\d{1,2})(january|february|march|april|may|june|july|august|september|october|november|december)(\d{2})',
        f, re.IGNORECASE
    )
    if m:
        d, mon, y = m.groups()
        mo = MONTH_MAP[mon.lower()]
        y  = '20' + y
        if valid(y, mo, d):
            return fmt(y, mo, d)

    # Pattern 7: DD-MM-YY with dashes (2-digit year)
    # e.g. Directive_28-9-10, -08-07-10, -1-8-10
    m = re.search(r'[-_](\d{1,2})-(\d{1,2})-(\d{2})(?:[-_.]|$)', f)
    if m:
        d, mo, y = m.groups()
        y = '20' + y
        if valid(y, mo, d):
            return fmt(y, mo, d)

    # Pattern 8: DDMmmYY at end with optional suffix
    # e.g. Directive-01Dec08, Directive-01Oct09-1
    m = re.search(
        r'(\d{1,2})(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(\d{2})(?:-\d+)?$',
        f, re.IGNORECASE
    )
    if m:
        d, mon, y = m.groups()
        mo = MONTH_MAP[mon.lower()]
        y  = '20' + y
        if valid(y, mo, d):
            return fmt(y, mo, d)

    # Pattern 9: DD_FullMonth_YYYY
    # e.g. 10_December_2012
    m = re.search(
        r'(\d{1,2})_(january|february|march|april|may|june|july|august|september|october|november|december)_(20\d{2})',
        f, re.IGNORECASE
    )
    if m:
        d, mon, y = m.groups()
        mo = MONTH_MAP[mon.lower()]
        if valid(y, mo, d):
            return fmt(y, mo, d)

    # Pattern 10: NBR_YYYYMMDD_
    m = re.search(r'NBR_(\d{4})(\d{2})(\d{2})_', f)
    if m:
        y, mo, d = m.groups()
        if valid(y, mo, d):
            return fmt(y, mo, d)

    # Pattern 11: Year only (4 digits)
    m = re.search(r'(20\d{2}|19\d{2})', f)
    if m:
        return m.group() + '-01-01'

    return ""


def fix_bsec():
    logger.info("--- Fixing BSEC dates ---")
    result = (
        supabase.table("documents")
        .select("id, primary_url, issue_date")
        .eq("issuing_body", "BSEC")
        .eq("issue_date", TODAY)
        .execute()
    )
    docs    = result.data
    fixed   = 0
    deleted = 0
    failed  = []

    logger.info(f"Found {len(docs)} BSEC docs with wrong date")

    for doc in docs:
        url    = doc["primary_url"]
        doc_id = doc["id"]

        # Delete empty URL records
        if not url or url.rstrip('/') in (
            "https://sec.gov.bd/slaws",
            "https://sec.gov.bd"
        ):
            supabase.table("documents").delete().eq("id", doc_id).execute()
            deleted += 1
            logger.info(f"  Deleted (empty URL)")
            continue

        new_date = get_date(url)

        if new_date:
            supabase.table("documents").update(
                {"issue_date": new_date}
            ).eq("id", doc_id).execute()
            fixed += 1
            logger.info(f"  Fixed: {url.split('/')[-1][:50]} -> {new_date}")
        else:
            failed.append(url)
            logger.warning(f"  No date: {url.split('/')[-1][:60]}")

    logger.info(f"BSEC: fixed={fixed} deleted={deleted} failed={len(failed)}")

    if failed:
        logger.info("Failed URLs:")
        for u in failed:
            logger.info(f"  {u.split('/')[-1]}")

    return fixed, deleted, failed


def fix_nbr():
    logger.info("--- Fixing NBR dates ---")
    result = (
        supabase.table("documents")
        .select("id, primary_url, title_en, issue_date")
        .eq("issuing_body", "NBR")
        .eq("issue_date", TODAY)
        .execute()
    )
    docs  = result.data
    fixed = 0
    failed = []

    logger.info(f"Found {len(docs)} NBR docs with wrong date")

    for doc in docs:
        url    = doc["primary_url"]
        title  = doc.get("title_en") or ""
        doc_id = doc["id"]

        new_date = get_date(url)

        # Fallback: extract year from title
        if not new_date:
            m = re.search(r'(20\d{2})', title)
            if m:
                new_date = m.group() + '-07-01'

        if new_date:
            supabase.table("documents").update(
                {"issue_date": new_date}
            ).eq("id", doc_id).execute()
            fixed += 1
            logger.info(f"  Fixed: {url.split('/')[-1][:50]} -> {new_date}")
        else:
            failed.append(url)
            logger.warning(f"  No date: {url.split('/')[-1][:60]}")

    logger.info(f"NBR: fixed={fixed} failed={len(failed)}")
    return fixed, failed


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Date Fix Script — BSEC and NBR")
    logger.info("=" * 60)

    fix_bsec()
    fix_nbr()

    # Final summary
    bsec_wrong = (
        supabase.table("documents")
        .select("id", count="exact")
        .eq("issuing_body", "BSEC")
        .eq("issue_date", TODAY)
        .execute()
    )
    nbr_wrong = (
        supabase.table("documents")
        .select("id", count="exact")
        .eq("issuing_body", "NBR")
        .eq("issue_date", TODAY)
        .execute()
    )

    logger.info("=" * 60)
    logger.info("FINAL RESULT")
    logger.info(f"  BSEC still wrong: {bsec_wrong.count}")
    logger.info(f"  NBR  still wrong: {nbr_wrong.count}")
    logger.info("=" * 60)