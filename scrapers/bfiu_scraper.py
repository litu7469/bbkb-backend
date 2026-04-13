import httpx
import re
import time
from bs4 import BeautifulSoup
from datetime import datetime, date
from loguru import logger
from app.database import supabase

# ── SEC (BSEC) base URL ───────────────────────────────────────
SEC_BASE     = "https://sec.gov.bd"
SEC_HOMEPAGE = "https://sec.gov.bd"

# ── Specific circular/law pages to scrape ────────────────────
BSEC_SOURCES = [
    {
        "url":      "https://sec.gov.bd/home/circular",
        "category": "Capital Markets & Securities",
        "doc_type": "Circular",
    },
    {
        "url":      "https://sec.gov.bd/home/laws",
        "category": "Capital Markets & Securities",
        "doc_type": "Securities Law",
    },
    {
        "url":      "https://sec.gov.bd/home/inotice",
        "category": "Capital Markets & Securities",
        "doc_type": "Caution Notice",
    },
]

# ── Keywords to identify regulatory documents ─────────────────
REGULATORY_KEYWORDS = [
    'circular', 'notification', 'order', 'rule', 'regulation',
    'directive', 'guideline', 'instruction', 'law', 'act',
    'exemption', 'approval', 'permission', 'suspension',
    'penalty', 'enforcement', 'compliance', 'amendment',
    'সার্কুলার', 'বিজ্ঞপ্তি', 'নির্দেশনা', 'আদেশ',
    'বিধি', 'প্রবিধান', 'নির্দেশ',
]

# ── Keywords to EXCLUDE (non-regulatory) ─────────────────────
EXCLUDE_KEYWORDS = [
    # Internal/administrative events
    'বিদায়', 'অনুষ্ঠান', 'সভার', 'নিয়োগ', 'পদোন্নতি',
    'farewell', 'seminar', 'workshop', 'training program',
    'recruitment', 'transfer', 'promotion',
    # Press releases
    'press release', 'press_release', 'প্রেস',
    # Tenders
    'tender', 'দরপত্র', 'quotation', 'procurement',
    # RTI (Right to Information — administrative)
    'right to information', 'তথ্য অধিকার আইন',
    # Panel lists — not circulars
    'panel of auditors', 'service providers panel',
    # Internal meeting minutes
    'কমিশন সভা', 'commission meeting',
]

# ── URL folders that contain regulatory documents ─────────────
REGULATORY_URL_FOLDERS = [
    '/slaws/',
    '/circular/',
    '/orders/',
    '/notice/',
    '/lbook/',
]

# ── URL folders to always skip ────────────────────────────────
SKIP_URL_FOLDERS = [
    '/press/',
    '/tender/',
    '/downloads/RTI',
    '/photo/',
    '/video/',
]

# ── Topic auto-tagging ────────────────────────────────────────
TOPIC_KEYWORDS = {
    "stock exchange":       ["stock exchange", "DSE", "CSE", "listing", "delisting"],
    "mutual fund":          ["mutual fund", "unit fund", "collective investment"],
    "IPO":                  ["IPO", "initial public offering", "public issue", "offer for sale"],
    "corporate governance": ["corporate governance", "board", "director", "AGM", "EGM"],
    "margin loan":          ["margin loan", "margin trading", "margin account"],
    "trading rules":        ["trading", "settlement", "clearing", "transaction"],
    "disclosure":           ["disclosure", "price sensitive", "financial statement", "material"],
    "penalty":              ["penalty", "fine", "enforcement", "suspension", "cancellation"],
    "bond/debenture":       ["bond", "debenture", "sukuk", "fixed income", "NRB bond"],
    "stockbroker":          ["broker", "dealer", "merchant banker", "portfolio manager"],
    "floor price":          ["floor price", "price limit", "circuit breaker"],
    "rights share":         ["rights share", "rights issue", "rights offering"],
}


def extract_topic_tags(title: str) -> list:
    tags  = []
    lower = title.lower()
    for tag, keywords in TOPIC_KEYWORDS.items():
        if any(kw.lower() in lower for kw in keywords):
            tags.append(tag)
    return tags if tags else ["general"]


def is_regulatory_document(title: str, url: str) -> bool:
    """
    Returns True only for genuine regulatory circulars/laws/orders.
    Returns False for press releases, tenders, internal events.
    """
    title_lower = title.lower()
    url_lower   = url.lower()

    # Always skip certain URL folders
    for folder in SKIP_URL_FOLDERS:
        if folder.lower() in url_lower:
            return False

    # Skip image files
    if any(url_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
        return False

    # Exclude by title keywords
    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in title_lower:
            return False

    # Accept if from a known regulatory URL folder
    for folder in REGULATORY_URL_FOLDERS:
        if folder.lower() in url_lower:
            return True

    # Accept if title contains a regulatory keyword
    for kw in REGULATORY_KEYWORDS:
        if kw.lower() in title_lower:
            return True

    # Default: reject if none of the above matched
    return False


def extract_date_from_url(url: str) -> str:
    """
    Extract actual document date from PDF filename.

    SEC URL patterns:
    Notification_09.02.2026.pdf  → 2026-02-09
    Order_15.01.2026.pdf         → 2026-01-15
    Circular_2024_03_15.pdf      → 2024-03-15
    """
    # Pattern 1: DD.MM.YYYY (most common in SEC filenames)
    m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', url)
    if m:
        d, mo, y = m.groups()
        try:
            # Validate it is a real date
            datetime(int(y), int(mo), int(d))
            return f"{y}-{mo}-{d}"
        except ValueError:
            pass

    # Pattern 2: YYYY-MM-DD or YYYY_MM_DD
    m = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})', url)
    if m:
        y, mo, d = m.groups()
        try:
            datetime(int(y), int(mo), int(d))
            return f"{y}-{mo}-{d}"
        except ValueError:
            pass

    # Pattern 3: Extract just the year from URL
    m = re.search(r'(20\d{2})', url)
    if m:
        return f"{m.group()}-01-01"

    return str(date.today())


def parse_date_text(date_str: str) -> str:
    """Parse date from table cell text."""
    if not date_str:
        return str(date.today())
    date_str = date_str.strip()
    for fmt in [
        "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
        "%d %B %Y", "%d %b %Y", "%B %d, %Y",
        "%d.%m.%Y", "%d/%m/%y",
    ]:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    y = re.search(r'\b(19|20)\d{2}\b', date_str)
    return f"{y.group()}-01-01" if y else str(date.today())


def build_sec_url(href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith('http'):
        return href
    if href.startswith('/'):
        return f"{SEC_BASE}{href}"
    return f"{SEC_BASE}/{href}"


def detect_language(title: str) -> str:
    bangla_chars = sum(1 for c in title if '\u0980' <= c <= '\u09FF')
    return "bangla" if bangla_chars > 2 else "english"


def detect_doc_type(url: str, default: str = "Circular") -> str:
    url_lower = url.lower()
    if '/slaws/' in url_lower:
        return "Securities Law/Notification"
    if '/orders/' in url_lower:
        return "Order"
    if '/notice/' in url_lower:
        return "Regulatory Notice"
    if '/lbook/' in url_lower:
        return "Law/Rule Book"
    if '/circular/' in url_lower:
        return "Circular"
    return default


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
        logger.info(f"  + [BSEC] {doc['issue_date']} | {doc['title_en'][:65]}")
        return True
    except Exception as e:
        logger.error(f"  Failed to save: {e}")
        return False


def scrape_sec_homepage(headers: dict) -> list:
    """
    Scrape regulatory PDF links directly from SEC homepage.
    SEC homepage shows recent notifications, orders, and circulars.
    """
    documents = []
    try:
        logger.info("Scraping SEC homepage for regulatory documents...")
        r = httpx.get(SEC_HOMEPAGE, headers=headers, timeout=30, follow_redirects=True)

        if r.status_code != 200:
            logger.warning(f"  HTTP {r.status_code}")
            return []

        soup      = BeautifulSoup(r.text, "html.parser")
        seen_urls = set()
        skipped   = 0

        for a in soup.find_all("a", href=True):
            href = a["href"]

            # Only process PDF links
            if ".pdf" not in href.lower():
                continue

            doc_url = build_sec_url(href)
            if not doc_url or doc_url in seen_urls:
                continue

            title = a.get_text(strip=True)
            if not title or len(title) < 3:
                # Try parent element for title
                parent = a.find_parent(['li', 'td', 'div', 'p'])
                if parent:
                    title = parent.get_text(strip=True)[:200]

            if not title or len(title) < 3:
                continue

            # Apply relevance filter
            if not is_regulatory_document(title, doc_url):
                skipped += 1
                logger.debug(f"  Skipped: {title[:50]}")
                continue

            seen_urls.add(doc_url)

            # Extract actual date from filename
            issue_date = extract_date_from_url(href)
            doc_type   = detect_doc_type(doc_url)
            language   = detect_language(title)

            doc = {
                "title_en":         title[:500],
                "title_bn":         None,
                "circular_ref":     f"BSEC {doc_type}",
                "issuing_body":     "BSEC",
                "department":       "BSEC",
                "doc_type":         doc_type,
                "issue_date":       issue_date,
                "status":           "active",
                "primary_url":      doc_url,
                "doc_format":       "pdf",
                "language":         language,
                "category_primary": "Capital Markets & Securities",
                "topic_tags":       extract_topic_tags(title),
                "added_by":         "scraper",
            }
            documents.append(doc)

        logger.info(f"  Homepage: {len(documents)} regulatory docs found, {skipped} skipped")

    except httpx.TimeoutException:
        logger.error("Timeout on SEC homepage")
    except Exception as e:
        logger.error(f"SEC homepage error: {e}")
        import traceback
        logger.error(traceback.format_exc())

    return documents


def scrape_sec_page(source: dict, headers: dict) -> list:
    """Scrape a specific SEC circular/law listing page."""
    documents = []
    try:
        logger.info(f"Scraping: {source['url']}")
        r = httpx.get(
            source["url"], headers=headers,
            timeout=30, follow_redirects=True
        )

        if r.status_code != 200:
            logger.warning(f"  HTTP {r.status_code} — skipping")
            return []

        soup      = BeautifulSoup(r.text, "html.parser")
        seen_urls = set()

        # ── Strategy 1: Table rows ────────────────────────
        rows = soup.find_all("tr")
        logger.info(f"  Rows found: {len(rows)}")

        for row in rows:
            tds = row.find_all("td")
            if len(tds) < 2:
                continue

            # Find PDF link in row
            doc_url = ""
            for a in row.find_all("a", href=True):
                href = a["href"]
                if ".pdf" in href.lower():
                    doc_url = build_sec_url(href)
                    break
            if not doc_url:
                for a in row.find_all("a", href=True):
                    href = a["href"]
                    if href and href != '#' and 'javascript' not in href.lower():
                        doc_url = build_sec_url(href)
                        break

            if not doc_url or doc_url in seen_urls:
                continue

            # Get title — longest meaningful text in row
            title = ""
            for td in tds:
                text = td.get_text(strip=True)
                if (len(text) > len(title)
                        and len(text) > 8
                        and not re.match(r'^[\d/\-\s\.]+$', text)):
                    title = text

            if not title or len(title) < 5:
                continue

            # Apply relevance filter
            if not is_regulatory_document(title, doc_url):
                continue

            seen_urls.add(doc_url)

            # Get date — try URL first, then table cell
            issue_date = extract_date_from_url(doc_url)
            if issue_date == str(date.today()):
                # Try extracting from table cells
                for td in tds:
                    text = td.get_text(strip=True)
                    if re.search(r'\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}', text):
                        parsed = parse_date_text(text)
                        if parsed != str(date.today()):
                            issue_date = parsed
                            break

            # Extract reference number if visible
            circ_ref  = f"BSEC {source['doc_type']}"
            ref_match = re.search(r'(BSEC[/\w\-\.]+\d{4})', title, re.IGNORECASE)
            if ref_match:
                circ_ref = ref_match.group(1).strip()

            doc_type = detect_doc_type(doc_url, source["doc_type"])
            language = detect_language(title)

            doc = {
                "title_en":         title[:500],
                "title_bn":         None,
                "circular_ref":     circ_ref,
                "issuing_body":     "BSEC",
                "department":       "BSEC",
                "doc_type":         doc_type,
                "issue_date":       issue_date,
                "status":           "active",
                "primary_url":      doc_url,
                "doc_format":       "pdf" if ".pdf" in doc_url.lower() else "html",
                "language":         language,
                "category_primary": source["category"],
                "topic_tags":       extract_topic_tags(title),
                "added_by":         "scraper",
            }
            documents.append(doc)

        # ── Strategy 2: Direct PDF links if no table ──────
        if not documents:
            logger.info("  No table rows — scanning all PDF links on page")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if ".pdf" not in href.lower():
                    continue

                doc_url = build_sec_url(href)
                if not doc_url or doc_url in seen_urls:
                    continue

                title = a.get_text(strip=True)
                if not title or len(title) < 3:
                    filename  = href.split("/")[-1]
                    filename  = re.sub(r'\.pdf$', '', filename, flags=re.IGNORECASE)
                    filename  = re.sub(r'[_\-]', ' ', filename).strip()
                    title     = filename.title()

                if not is_regulatory_document(title, doc_url):
                    continue

                seen_urls.add(doc_url)
                issue_date = extract_date_from_url(href)
                doc_type   = detect_doc_type(doc_url, source["doc_type"])

                doc = {
                    "title_en":         title[:500],
                    "title_bn":         None,
                    "circular_ref":     f"BSEC {doc_type}",
                    "issuing_body":     "BSEC",
                    "department":       "BSEC",
                    "doc_type":         doc_type,
                    "issue_date":       issue_date,
                    "status":           "active",
                    "primary_url":      doc_url,
                    "doc_format":       "pdf",
                    "language":         detect_language(title),
                    "category_primary": source["category"],
                    "topic_tags":       extract_topic_tags(title),
                    "added_by":         "scraper",
                }
                documents.append(doc)

        logger.info(f"  Extracted {len(documents)} regulatory documents")

    except httpx.TimeoutException:
        logger.error(f"  Timeout: {source['url']}")
    except Exception as e:
        logger.error(f"  Error scraping {source['url']}: {e}")
        import traceback
        logger.error(traceback.format_exc())

    return documents


def run_bsec_scraper():
    logger.info("=" * 60)
    logger.info("BSEC / SEC Scraper — Starting")
    logger.info("=" * 60)

    job = supabase.table("scraper_jobs").insert({
        "source":     "BSEC",
        "started_at": datetime.utcnow().isoformat(),
        "status":     "running",
    }).execute()
    job_id = job.data[0]["id"] if job.data else None

    headers = {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer":         "https://sec.gov.bd",
    }

    total_found = 0
    total_new   = 0
    all_errors  = []

    # ── Step 1: Scrape SEC homepage (recent docs) ─────────
    try:
        docs         = scrape_sec_homepage(headers)
        total_found += len(docs)
        for doc in docs:
            if save_document(doc):
                total_new += 1
        time.sleep(2)
    except Exception as e:
        msg = f"Homepage error: {e}"
        logger.error(msg)
        all_errors.append(msg)

    # ── Step 2: Scrape specific circular pages ────────────
    for source in BSEC_SOURCES:
        try:
            docs         = scrape_sec_page(source, headers)
            total_found += len(docs)
            for doc in docs:
                if save_document(doc):
                    total_new += 1
            time.sleep(2)
        except Exception as e:
            msg = f"Error on {source['url']}: {e}"
            logger.error(msg)
            all_errors.append(msg)

    # ── Update job log ────────────────────────────────────
    if job_id:
        supabase.table("scraper_jobs").update({
            "completed_at": datetime.utcnow().isoformat(),
            "status":       "completed",
            "docs_found":   total_found,
            "docs_new":     total_new,
            "errors":       all_errors if all_errors else None,
        }).eq("id", job_id).execute()

    logger.info("=" * 60)
    logger.info("BSEC Scraper finished!")
    logger.info(f"  Found : {total_found}")
    logger.info(f"  New   : {total_new}")
    logger.info(f"  Errors: {len(all_errors)}")
    logger.info("=" * 60)

    return {"found": total_found, "new": total_new, "errors": len(all_errors)}


if __name__ == "__main__":
    result = run_bsec_scraper()
    print(f"\nResult: {result}")