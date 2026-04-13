import httpx
import re
import time
from bs4 import BeautifulSoup
from datetime import datetime, date
from loguru import logger
from app.database import supabase

# ── NBR Sources ───────────────────────────────────────────────
#
# Two different table structures on NBR website:
#
# TYPE A — SROs and General Orders (confirmed structure):
# Col 0: Serial number
# Col 1: Circular reference + PDF link
# Col 2: Date DD/MM/YYYY
# Col 3: Title/subject
#
# TYPE B — Publications page (different structure):
# Col 0: Empty or image
# Col 1: Title + "Publish Date: XX" mixed in same cell
#        Link is in Col 1
#
NBR_SOURCES = [
    {
        "url":      "https://nbr.gov.bd/regulations/sros/income-tax-sros/eng",
        "category": "Income Tax",
        "doc_type": "SRO",
        "dept":     "Income Tax",
        "type":     "A",
    },
    {
        "url":      "https://nbr.gov.bd/regulations/sros/vat-sros/eng",
        "category": "VAT",
        "doc_type": "SRO",
        "dept":     "VAT",
        "type":     "A",
    },
    {
        "url":      "https://nbr.gov.bd/regulations/sros/customs-sros/eng",
        "category": "Customs",
        "doc_type": "SRO",
        "dept":     "Customs",
        "type":     "A",
    },
    {
        "url":      "https://nbr.gov.bd/regulations/gos/income-tax-gos/eng",
        "category": "Income Tax",
        "doc_type": "General Order",
        "dept":     "Income Tax",
        "type":     "A",
    },
    {
        "url":      "https://nbr.gov.bd/regulations/gos/vat-gos/eng",
        "category": "VAT",
        "doc_type": "General Order",
        "dept":     "VAT",
        "type":     "A",
    },
    {
        "url":      "https://nbr.gov.bd/regulations/gos/customs-gos/eng",
        "category": "Customs",
        "doc_type": "General Order",
        "dept":     "Customs",
        "type":     "A",
    },
    {
        "url":      "https://nbr.gov.bd/information-library/lrpcgbd/eng",
        "category": "General",
        "doc_type": "Circular/Guideline",
        "dept":     "General",
        "type":     "A",
    },
]

# ── Keywords to exclude ───────────────────────────────────────
EXCLUDE_KEYWORDS = [
    'tender', 'দরপত্র', 'quotation',
    'press release', 'প্রেস',
    'বিদায়', 'অনুষ্ঠান',
    'recruitment', 'vacancy', 'নিয়োগ',
    'transfer posting', 'বদলি',
    'photo', 'video', 'gallery',
    'publish date',          # catch leftover garbage
    'gradation list',        # administrative list
    'looking back',          # retrospective publications
    'PPT on', 'ppt on',      # presentation files
]

EXCLUDE_FILE_TYPES = ['.xls', '.xlsx', '.ppt', '.pptx', '.doc']

TOPIC_KEYWORDS = {
    "income tax":       ["income tax", "আয়কর", "TDS", "withholding", "TIN"],
    "VAT":              ["VAT", "মূসক", "value added tax", "mushak"],
    "customs":          ["customs", "কাস্টমস", "import duty", "tariff", "shipping"],
    "tax exemption":    ["exemption", "অব্যাহতি", "rebate", "relief"],
    "penalty":          ["penalty", "জরিমানা", "fine"],
    "tax return":       ["return", "রিটার্ন", "filing", "e-return"],
    "withholding tax":  ["withholding", "উৎসে কর", "TDS"],
    "budget":           ["budget", "বাজেট", "finance act", "paripatra"],
    "SRO":              ["SRO", "এস.আর.ও"],
    "amendment":        ["amendment", "সংশোধন", "amended"],
}


def extract_topic_tags(title: str) -> list:
    tags  = []
    lower = title.lower()
    for tag, kws in TOPIC_KEYWORDS.items():
        if any(kw.lower() in lower for kw in kws):
            tags.append(tag)
    return tags if tags else ["general"]


def is_relevant(title: str, url: str) -> bool:
    """Filter out non-regulatory documents."""
    if not title or len(title) < 5:
        return False
    title_lower = title.lower()

    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in title_lower:
            return False

    # Skip non-document file types
    for ext in EXCLUDE_FILE_TYPES:
        if url.lower().endswith(ext):
            return False

    # Skip public notices (press releases etc)
    if '/uploads/public-notice/' in url.lower():
        return False

    # Skip if URL is just the homepage
    if url.rstrip('/') in ('https://nbr.gov.bd', 'http://nbr.gov.bd'):
        return False

    return True


def parse_date_nbr(date_str: str) -> str:
    """
    Parse NBR date formats:
    DD/MM/YYYY → most common e.g. 24/09/2025
    DD-MM-YYYY → e.g. 05-12-2022
    DD/MM/YY   → e.g. 06/09/16
    """
    if not date_str:
        return ""

    date_str = date_str.strip()

    # Clean up — remove non-date characters
    date_str = re.sub(r'[^\d/\-\.]', '', date_str).strip('/')

    if not date_str:
        return ""

    # DD/MM/YYYY
    m = re.match(r'^(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})$', date_str)
    if m:
        d, mo, y = m.groups()
        try:
            datetime(int(y), int(mo), int(d))
            return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
        except ValueError:
            pass

    # DD/MM/YY
    m = re.match(r'^(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2})$', date_str)
    if m:
        d, mo, y = m.groups()
        y = '20' + y
        try:
            datetime(int(y), int(mo), int(d))
            return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
        except ValueError:
            pass

    return ""


def extract_date_from_text(text: str) -> str:
    """
    Extract date from mixed text like:
    'Some title Publish Date : ২৮/০১/২০১৪ Some description'
    '03/05/2016'
    """
    # Look for date pattern in text
    patterns = [
        r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})',  # DD/MM/YYYY
        r'(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})',  # YYYY/MM/DD
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            groups = m.groups()
            # Check if first group is year (4 digits)
            if len(groups[0]) == 4:
                y, mo, d = groups
            else:
                d, mo, y = groups
            try:
                datetime(int(y), int(mo), int(d))
                return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
            except ValueError:
                continue

    # Try Bangla digits (০-৯) — convert to ASCII
    bangla_to_ascii = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')
    ascii_text = text.translate(bangla_to_ascii)
    for pattern in patterns:
        m = re.search(pattern, ascii_text)
        if m:
            groups = m.groups()
            if len(groups[0]) == 4:
                y, mo, d = groups
            else:
                d, mo, y = groups
            try:
                datetime(int(y), int(mo), int(d))
                return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
            except ValueError:
                continue

    return ""


def extract_date_from_url(url: str) -> str:
    """Extract date from NBR PDF filename."""
    # NBR_YYYYMMDD_XXXX.pdf
    m = re.search(r'NBR_(\d{4})(\d{2})(\d{2})_', url)
    if m:
        y, mo, d = m.groups()
        try:
            datetime(int(y), int(mo), int(d))
            return f"{y}-{mo}-{d}"
        except ValueError:
            pass

    # DD_MonthName_YYYY in filename
    m = re.search(r'(\d{1,2})_(\w+)_(\d{4})', url, re.IGNORECASE)
    if m:
        d, month_name, y = m.groups()
        try:
            dt = datetime.strptime(f"{d} {month_name} {y}", "%d %B %Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Just YYYY
    m = re.search(r'(20\d{2})', url)
    if m:
        return f"{m.group()}-01-01"

    return ""


def build_nbr_url(href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith('http'):
        return href
    if href.startswith('/'):
        return f"https://nbr.gov.bd{href}"
    return f"https://nbr.gov.bd/{href}"


def detect_language(title: str) -> str:
    bangla_chars = sum(1 for c in title if '\u0980' <= c <= '\u09FF')
    return "bangla" if bangla_chars > 2 else "english"


def document_exists(url: str) -> bool:
    result = (
        supabase.table("documents")
        .select("id")
        .eq("primary_url", url)
        .execute()
    )
    return len(result.data) > 0


def save_document(doc: dict) -> bool:
    try:
        if document_exists(doc["primary_url"]):
            return False
        supabase.table("documents").insert(doc).execute()
        logger.info(
            f"  + [NBR/{doc['department']}] "
            f"{doc['issue_date']} | "
            f"{doc['title_en'][:60]}"
        )
        return True
    except Exception as e:
        logger.error(f"  Failed to save: {e}")
        return False


def scrape_type_a(source: dict, soup: BeautifulSoup) -> list:
    """
    Type A pages: SROs and General Orders
    Col 0: Serial | Col 1: Ref+Link | Col 2: Date | Col 3: Title
    """
    documents = []
    seen_urls = set()
    skipped   = 0

    rows = soup.find_all("tr")

    for row in rows:
        # Skip header rows
        if row.find('th'):
            continue

        tds = row.find_all("td")
        if len(tds) < 3:
            continue

        # Col 0: Serial number — skip if just digits
        col0 = tds[0].get_text(strip=True)
        if not re.match(r'^\d+$', col0) and len(tds) < 4:
            continue

        # Col 1: Reference number + PDF link
        ref_td   = tds[1]
        circ_ref = ref_td.get_text(strip=True)

        # Skip if reference is just a serial number
        if re.match(r'^\d+$', circ_ref):
            continue

        # Get PDF URL from Col 1
        doc_url = ""
        for a in ref_td.find_all("a", href=True):
            href = a["href"]
            if (href and href != '#'
                    and 'javascript' not in href.lower()
                    and href.rstrip('/') != 'https://nbr.gov.bd'):
                doc_url = build_nbr_url(href)
                break

        # Fallback: search whole row
        if not doc_url:
            for a in row.find_all("a", href=True):
                href = a["href"]
                if (href and href != '#'
                        and 'javascript' not in href.lower()
                        and href.rstrip('/') != 'https://nbr.gov.bd'):
                    doc_url = build_nbr_url(href)
                    break

        if not doc_url or doc_url in seen_urls:
            continue

        # Col 2: Date (DD/MM/YYYY confirmed)
        date_text  = tds[2].get_text(strip=True) if len(tds) > 2 else ""
        issue_date = parse_date_nbr(date_text)

        # If no date in Col 2 — try URL
        if not issue_date:
            issue_date = extract_date_from_url(doc_url)

        # Final fallback — year only from URL
        if not issue_date:
            issue_date = str(date.today())

        # Col 3: Title/Subject
        title = ""
        if len(tds) > 3:
            title = tds[3].get_text(strip=True)

        # Fallback: use reference as title
        if not title or len(title) < 3:
            title = circ_ref

        # Clean title — remove any "Publish Date" remnants
        title = re.sub(r'Publish Date\s*:.*$', '', title, flags=re.IGNORECASE).strip()
        title = re.sub(r'\s+', ' ', title).strip()

        if not is_relevant(title, doc_url):
            skipped += 1
            continue

        seen_urls.add(doc_url)

        documents.append({
            "title_en":         title[:500],
            "title_bn":         None,
            "circular_ref":     circ_ref[:200],
            "issuing_body":     "NBR",
            "department":       source["dept"],
            "doc_type":         source["doc_type"],
            "issue_date":       issue_date,
            "status":           "active",
            "primary_url":      doc_url,
            "doc_format":       "pdf" if ".pdf" in doc_url.lower() else "html",
            "language":         detect_language(title),
            "category_primary": f"Tax — {source['category']}",
            "topic_tags":       extract_topic_tags(title),
            "added_by":         "scraper",
        })

    logger.info(f"  Type A: {len(documents)} extracted, {skipped} skipped")
    return documents


def scrape_nbr_page(source: dict, headers: dict) -> list:
    try:
        logger.info(f"Scraping [{source['type']}]: {source['url']}")
        r = httpx.get(
            source["url"],
            headers=headers,
            timeout=30,
            follow_redirects=True
        )

        if r.status_code != 200:
            logger.warning(f"  HTTP {r.status_code} — skipping")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        return scrape_type_a(source, soup)

    except httpx.TimeoutException:
        logger.error(f"  Timeout: {source['url']}")
        return []
    except Exception as e:
        logger.error(f"  Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return []


def run_nbr_scraper():
    logger.info("=" * 60)
    logger.info("NBR Scraper — Starting")
    logger.info("=" * 60)

    job = supabase.table("scraper_jobs").insert({
        "source":     "NBR",
        "started_at": datetime.utcnow().isoformat(),
        "status":     "running",
    }).execute()
    job_id = job.data[0]["id"] if job.data else None

    headers = {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer":         "https://nbr.gov.bd",
    }

    total_found = 0
    total_new   = 0
    all_errors  = []

    for source in NBR_SOURCES:
        try:
            docs         = scrape_nbr_page(source, headers)
            total_found += len(docs)
            for doc in docs:
                if save_document(doc):
                    total_new += 1
            time.sleep(2)
        except Exception as e:
            msg = f"Error on {source['url']}: {e}"
            logger.error(msg)
            all_errors.append(msg)

    if job_id:
        supabase.table("scraper_jobs").update({
            "completed_at": datetime.utcnow().isoformat(),
            "status":       "completed",
            "docs_found":   total_found,
            "docs_new":     total_new,
            "errors":       all_errors if all_errors else None,
        }).eq("id", job_id).execute()

    logger.info("=" * 60)
    logger.info("NBR Scraper finished!")
    logger.info(f"  Found : {total_found}")
    logger.info(f"  New   : {total_new}")
    logger.info(f"  Errors: {len(all_errors)}")
    logger.info("=" * 60)

    return {"found": total_found, "new": total_new, "errors": len(all_errors)}


if __name__ == "__main__":
    result = run_nbr_scraper()
    print(f"\nResult: {result}")