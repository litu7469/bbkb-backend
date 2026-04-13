import httpx
import re
import time
from bs4 import BeautifulSoup
from datetime import datetime, date
from loguru import logger
from app.database import supabase

# ── Single source — BB lists ALL circulars on one page ────────
# We confirmed from HTML: one table with Date | Title | English | Bangla
BB_MAIN_URL = "https://www.bb.org.bd/en/index.php/mediaroom/circular/brpd"

# All BB circular listing pages (some may have separate pages)
BB_SOURCES = [
    {
        "url":        "https://www.bb.org.bd/en/index.php/mediaroom/circular/brpd",
        "label":      "BB Circulars (All Departments)",
        "default_category": "Banking Operations",
    },
]

# ── Department detection from circular_ref prefix ─────────────
DEPT_MAP = {
    # Core departments
    "BRPD":     { "dept": "BRPD",     "category": "Credit Policy & Lending"               },
    "BRPD-1":   { "dept": "BRPD",     "category": "Credit Policy & Lending"               },
    "BRPD-2":   { "dept": "BRPD",     "category": "Credit Policy & Lending"               },
    "DOS":      { "dept": "DOS",      "category": "Banking Operations"                    },
    "DOS-1":    { "dept": "DOS",      "category": "Banking Operations"                    },
    "DFIM":     { "dept": "DFIM",     "category": "NBFI & Leasing"                        },
    "FID":      { "dept": "DFIM",     "category": "NBFI & Leasing"                        },
    "FEPD":     { "dept": "FEPD",     "category": "Foreign Exchange & Remittance"         },
    "FEPD-1":   { "dept": "FEPD",     "category": "Foreign Exchange & Remittance"         },
    "FEOD":     { "dept": "FEOD",     "category": "Foreign Exchange & Remittance"         },
    "FEID":     { "dept": "FEID",     "category": "Foreign Exchange & Remittance"         },
    "BFIU":     { "dept": "BFIU",     "category": "Anti-Money Laundering & CFT"           },
    "PSD":      { "dept": "PSD",      "category": "Digital Banking & Fintech"             },
    "PSD-1":    { "dept": "PSD",      "category": "Digital Banking & Fintech"             },
    "PSD-2":    { "dept": "PSD",      "category": "Digital Banking & Fintech"             },
    "MPD":      { "dept": "MPD",      "category": "Monetary Policy"                       },
    "SME":      { "dept": "SME",      "category": "Credit Policy & Lending"               },
    "SMESPD":   { "dept": "SME",      "category": "Credit Policy & Lending"               },
    "HRD":      { "dept": "HRD",      "category": "Banking Operations"                    },
    "ICT":      { "dept": "ICT",      "category": "Banking Operations"                    },
    # New departments found from URL analysis
    "SDAD":     { "dept": "SDAD",     "category": "Banking Operations"                    },
    "DMD":      { "dept": "DMD",      "category": "Banking Operations"                    },
    "SPCD":     { "dept": "SPCD",     "category": "Credit Policy & Lending"               },
    "GBCSRD":   { "dept": "GBCSRD",   "category": "Green Banking & Sustainable Finance"   },
    "GBCRD":    { "dept": "GBCSRD",   "category": "Green Banking & Sustainable Finance"   },
    "SFD":      { "dept": "GBCSRD",   "category": "Green Banking & Sustainable Finance"   },
    "DCMPS":    { "dept": "DCMPS",    "category": "Banking Operations"                    },
    "ACFID":    { "dept": "ACFID",    "category": "Banking Operations"                    },
    "FININCLD": { "dept": "FININCLD", "category": "Banking Operations"                    },
    "FIN":      { "dept": "FININCLD", "category": "Banking Operations"                    },
    "LAW":      { "dept": "LAW",      "category": "Acts & Legislation"                    },
}
# ── Topic auto-tagging ────────────────────────────────────────
TOPIC_KEYWORDS = {
    "loan classification":  ["classification", "provisioning", "NPL", "loan"],
    "AML/CFT":              ["money laundering", "AML", "CFT", "terrorist", "suspicious"],
    "capital adequacy":     ["capital", "CRAR", "Basel", "adequacy"],
    "foreign exchange":     ["foreign exchange", "remittance", "NRB", "export", "import", "LPG", "inward"],
    "digital banking":      ["mobile", "internet banking", "fintech", "MFS", "digital", "payment"],
    "KYC":                  ["KYC", "know your customer", "CDD", "due diligence"],
    "SME":                  ["SME", "small enterprise", "medium enterprise"],
    "green banking":        ["green", "sustainable", "ESG", "climate"],
    "Islamic banking":      ["Islamic", "Shariah", "mudaraba", "musharaka"],
    "interest rate":        ["interest rate", "lending rate", "deposit rate"],
    "CRR/SLR":              ["CRR", "SLR", "cash reserve", "statutory liquidity"],
    "corporate governance": ["governance", "board", "director", "CEO"],
    "refinance":            ["refinance", "refinancing", "pre-shipment", "post-shipment"],
    "remittance":           ["remittance", "inward remittance", "outward remittance"],
    "election":             ["election", "parliament", "constituency"],
    "CMMS":                 ["CMMS", "corporate memory", "penalized"],
}

def extract_topic_tags(title: str) -> list:
    tags  = []
    lower = title.lower()
    for tag, keywords in TOPIC_KEYWORDS.items():
        if any(kw.lower() in lower for kw in keywords):
            tags.append(tag)
    return tags if tags else ["general"]

def detect_dept_from_ref(circular_ref: str, pdf_url: str = "") -> dict:
    """
    Detect department and category from circular reference prefix.
    Falls back to PDF URL folder name if ref prefix not recognised.
    """
    default = {"dept": "BB", "category": "Banking Operations"}

    if not circular_ref:
        return detect_dept_from_url(pdf_url) if pdf_url else default

    # Get the first token before any space
    first_token = circular_ref.strip().split()[0].upper()

    # Try exact match
    if first_token in DEPT_MAP:
        return DEPT_MAP[first_token]

    # Try stripping trailing digits/hyphens: 'BRPD-1' → 'BRPD'
    base = re.sub(r'[-\d]+$', '', first_token)
    if base in DEPT_MAP:
        return DEPT_MAP[base]

    # Try partial prefix match
    for key in sorted(DEPT_MAP.keys(), key=len, reverse=True):
        if first_token.startswith(key):
            return DEPT_MAP[key]

    # Fall back to URL-based detection
    if pdf_url:
        return detect_dept_from_url(pdf_url)

    return default


def detect_dept_from_url(pdf_url: str) -> dict:
    """
    Detect department from the PDF URL folder name.

    BB URL pattern:
    https://www.bb.org.bd/mediaroom/circulars/{folder}/{filename}.pdf

    Folder → Department mapping:
    brpd      → BRPD
    fepd      → FEPD
    fid       → DFIM
    aml       → BFIU
    psd       → PSD
    psd-2     → PSD
    mpd       → MPD
    smespd    → SME
    sdad      → SDAD
    dmd       → DMD
    spcd      → SPCD
    gbcrd     → GBCSRD
    finincld  → FININCLD
    feod      → FEOD
    feid      → FEID
    """
    URL_FOLDER_MAP = {
        "brpd":     { "dept": "BRPD",     "category": "Credit Policy & Lending"             },
        "brpd-1":   { "dept": "BRPD",     "category": "Credit Policy & Lending"             },
        "brpd-2":   { "dept": "BRPD",     "category": "Credit Policy & Lending"             },
        "dos":      { "dept": "DOS",      "category": "Banking Operations"                  },
        "fepd":     { "dept": "FEPD",     "category": "Foreign Exchange & Remittance"       },
        "fid":      { "dept": "DFIM",     "category": "NBFI & Leasing"                      },
        "dfim":     { "dept": "DFIM",     "category": "NBFI & Leasing"                      },
        "aml":      { "dept": "BFIU",     "category": "Anti-Money Laundering & CFT"         },
        "psd":      { "dept": "PSD",      "category": "Digital Banking & Fintech"           },
        "psd-1":    { "dept": "PSD",      "category": "Digital Banking & Fintech"           },
        "psd-2":    { "dept": "PSD",      "category": "Digital Banking & Fintech"           },
        "mpd":      { "dept": "MPD",      "category": "Monetary Policy"                     },
        "smespd":   { "dept": "SME",      "category": "Credit Policy & Lending"             },
        "sdad":     { "dept": "SDAD",     "category": "Banking Operations"                  },
        "dmd":      { "dept": "DMD",      "category": "Banking Operations"                  },
        "spcd":     { "dept": "SPCD",     "category": "Credit Policy & Lending"             },
        "gbcrd":    { "dept": "GBCSRD",   "category": "Green Banking & Sustainable Finance" },
        "gbcsrd":   { "dept": "GBCSRD",   "category": "Green Banking & Sustainable Finance" },
        "finincld": { "dept": "FININCLD", "category": "Banking Operations"                  },
        "feod":     { "dept": "FEOD",     "category": "Foreign Exchange & Remittance"       },
        "feid":     { "dept": "FEID",     "category": "Foreign Exchange & Remittance"       },
    }

    if not pdf_url:
        return {"dept": "BB", "category": "Banking Operations"}

    # Extract folder from URL
    # e.g. https://www.bb.org.bd/mediaroom/circulars/brpd/apr092026brpd.pdf
    #                                                 ^^^^  ← this part
    try:
        parts  = pdf_url.rstrip('/').split('/')
        folder = parts[-2].lower()  # second-to-last segment is the folder

        if folder in URL_FOLDER_MAP:
            return URL_FOLDER_MAP[folder]

        # Try without trailing numbers: 'psd-2' → 'psd'
        base_folder = re.sub(r'-\d+$', '', folder)
        if base_folder in URL_FOLDER_MAP:
            return URL_FOLDER_MAP[base_folder]

    except (IndexError, AttributeError):
        pass

    return {"dept": "BB", "category": "Banking Operations"}
    # Get the first token before any space
    first_token = circular_ref.strip().split()[0].upper()

    # Try exact match first
    if first_token in DEPT_MAP:
        return DEPT_MAP[first_token]

    # Try stripping trailing numbers/hyphens: 'BRPD-1' → 'BRPD'
    base = re.sub(r'[-\d]+$', '', first_token)
    if base in DEPT_MAP:
        return DEPT_MAP[base]

    # Try partial match
    for key in DEPT_MAP:
        if first_token.startswith(key):
            return DEPT_MAP[key]

    return {"dept": "BB", "category": "Banking Operations"}

def parse_date_bb(date_str: str) -> str:
    """
    Parse BB date format.
    BB uses DD/MM/YY e.g. '09/04/26' = 9 April 2026
    """
    if not date_str:
        return str(date.today())

    date_str = date_str.strip()

    # DD/MM/YY or DD/MM/YYYY
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$', date_str)
    if m:
        day, month, year = m.groups()
        if len(year) == 2:
            year = '20' + year
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    # Try other common formats
    for fmt in ["%d %B %Y", "%d-%m-%Y", "%d/%m/%Y", "%B %d, %Y", "%d %b %Y"]:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Extract year as last resort
    y = re.search(r'\b(19|20)\d{2}\b', date_str)
    return f"{y.group()}-01-01" if y else str(date.today())

def split_title_and_ref(raw_title: str) -> tuple:
    """
    Split BB circular title into (circular_ref, clean_subject).

    BB format: 'DEPT[-N] Circular [Letter] No. NN: Subject of circular'
    e.g. 'FEPD-1 Circular Letter No. 01: Import of LPG under supplier credit'
      → ref   = 'FEPD-1 Circular Letter No. 01'
      → title = 'Import of LPG under supplier credit'

    e.g. 'BRPD Circular No. 14: Guidelines on Loan Classification'
      → ref   = 'BRPD Circular No. 14'
      → title = 'Guidelines on Loan Classification'
    """
    raw_title = raw_title.strip()

    if ':' in raw_title:
        colon_pos = raw_title.index(':')
        before    = raw_title[:colon_pos].strip()
        after     = raw_title[colon_pos + 1:].strip()

        # Validate before-colon looks like a circular reference
        looks_like_ref = (
            len(before) < 80
            and len(after) > 3
            and any(kw in before.upper() for kw in ['CIRCULAR', 'NO.', 'NO '])
        )

        if looks_like_ref:
            return before, after

    # No colon — whole string is title, generate a ref
    # Try to find ref pattern in string
    m = re.search(
        r'([A-Z]+(?:-\d+)?\s+Circular(?:\s+Letter)?\s+No\.?\s*[\d/]+)',
        raw_title, re.IGNORECASE
    )
    if m:
        ref = m.group(1).strip()
        # Remove the ref part from title
        remaining = raw_title.replace(m.group(0), '').strip(' :-')
        if remaining:
            return ref, remaining

    return raw_title, raw_title  # fallback: use full string for both

def build_full_url(href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith('http'):
        return href
    if href.startswith('/'):
        return f"https://www.bb.org.bd{href}"
    return f"https://www.bb.org.bd/{href}"

def get_pdf_link_from_td(td) -> str:
    """Extract the best PDF URL from a table cell."""
    if not td:
        return ""

    text = td.get_text(strip=True).lower()
    if text in ('not available', 'n/a', ''):
        return ""

    # Check pdf-link attribute first (BB uses this on anchor tags)
    for a in td.find_all('a'):
        pdf_link = a.get('pdf-link', '')
        if pdf_link:
            return build_full_url(pdf_link)

    # Then check href
    for a in td.find_all('a', href=True):
        href = a['href']
        if href and href != '#' and 'javascript' not in href.lower():
            return build_full_url(href)

    return ""

def document_exists(url: str) -> bool:
    result = (
        supabase.table("documents")
        .select("id")
        .eq("primary_url", url)
        .execute()
    )
    return len(result.data) > 0

def save_document(doc_data: dict) -> bool:
    try:
        if document_exists(doc_data["primary_url"]):
            return False
        supabase.table("documents").insert(doc_data).execute()
        logger.info(f"  + [{doc_data['department']}] {doc_data['circular_ref']} | {doc_data['title_en'][:60]}")
        return True
    except Exception as e:
        logger.error(f"  Failed to save: {e}")
        return False

def scrape_bb_circular_page(url: str, headers: dict) -> list:
    """
    Scrape a BB circular listing page.

    Confirmed HTML structure:
    <tr>
      <th>Date</th>
      <th>Title</th>          ← col 1: full title with ref prefix
      <th>English</th>        ← col 2: English PDF link
      <th>Bangla</th>         ← col 3: Bangla PDF link
    </tr>
    <tr>
      <td>09/04/26</td>
      <td class="text-left">DEPT Circular No. XX: Subject here</td>
      <td><a pdf-link="...en.pdf">English</a><br><a href="...">Download</a></td>
      <td><a pdf-link="...bn.pdf">Bangla</a><br><a href="...">Download</a></td>
    </tr>
    """
    documents = []

    try:
        response = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
        if response.status_code != 200:
            logger.warning(f"  HTTP {response.status_code} for {url}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.find_all("tr")
        logger.info(f"  {len(rows)} rows found on page")

        seen_urls = set()

        for row in rows:
            tds = row.find_all("td")

            # Need at least 2 columns (date + title)
            if len(tds) < 2:
                continue

            # ── Col 0: Date ───────────────────────────────
            date_str   = tds[0].get_text(strip=True)
            issue_date = parse_date_bb(date_str)

            # ── Col 1: Title (class="text-left") ─────────
            raw_title = tds[1].get_text(strip=True)

            # Skip header rows and empty rows
            if not raw_title or raw_title.lower() in ('title', 'subject', 'circular', ''):
                continue
            if len(raw_title) < 5:
                continue

            # ── Col 2: English PDF ────────────────────────
            en_url = get_pdf_link_from_td(tds[2]) if len(tds) > 2 else ""

            # ── Col 3: Bangla PDF ─────────────────────────
            bn_url = get_pdf_link_from_td(tds[3]) if len(tds) > 3 else ""

            # Must have at least one PDF URL
            primary_url = en_url or bn_url
            if not primary_url:
                continue

            # Skip duplicates
            if primary_url in seen_urls:
                continue
            seen_urls.add(primary_url)

            # ── Split into ref + clean title ──────────────
            circ_ref, clean_title = split_title_and_ref(raw_title)

            # ── Detect department from circular_ref ───────
            dept_info  = detect_dept_from_ref(circ_ref, primary_url)
                 department = dept_info["dept"]
                 category   = dept_info["category"]

            # ── Build document record ─────────────────────
            doc = {
                "title_en":         clean_title,
                "title_bn":         None,
                "circular_ref":     circ_ref,
                "issuing_body":     "BB",
                "department":       department,
                "doc_type":         "Circular",
                "issue_date":       issue_date,
                "status":           "active",
                "primary_url":      primary_url,
                "mirror_url":       bn_url if bn_url and bn_url != primary_url else None,
                "doc_format":       "pdf",
                "language":         "english",
                "category_primary": category,
                "topic_tags":       extract_topic_tags(clean_title),
                "added_by":         "scraper",
            }
            documents.append(doc)

    except httpx.TimeoutException:
        logger.error(f"  Timeout: {url}")
    except Exception as e:
        logger.error(f"  Error scraping {url}: {e}")
        import traceback
        logger.error(traceback.format_exc())

    return documents

def get_all_bb_pages(base_url: str, headers: dict) -> list:
    """
    Get all pages from a BB circular listing.
    BB uses pagination — check if there are multiple pages.
    """
    all_docs = []

    # Page 1
    logger.info(f"Scraping page 1: {base_url}")
    docs = scrape_bb_circular_page(base_url, headers)
    all_docs.extend(docs)
    logger.info(f"  Got {len(docs)} documents")

    # Check for pagination
    try:
        response = httpx.get(base_url, headers=headers, timeout=30, follow_redirects=True)
        soup = BeautifulSoup(response.text, "html.parser")

        # Look for pagination links
        pagination = soup.find('ul', class_='pagination')
        if not pagination:
            pagination = soup.find('div', class_='pagination')

        if pagination:
            page_links = pagination.find_all('a', href=True)
            page_numbers = set()
            for link in page_links:
                href = link.get('href', '')
                # Look for page number in URL
                m = re.search(r'[?&]page=(\d+)|/page/(\d+)', href)
                if m:
                    page_num = int(m.group(1) or m.group(2))
                    page_numbers.add(page_num)

            for page_num in sorted(page_numbers):
                if '?' in base_url:
                    page_url = f"{base_url}&page={page_num}"
                else:
                    page_url = f"{base_url}?page={page_num}"

                logger.info(f"Scraping page {page_num}: {page_url}")
                time.sleep(2)
                docs = scrape_bb_circular_page(page_url, headers)
                all_docs.extend(docs)
                logger.info(f"  Got {len(docs)} documents")

    except Exception as e:
        logger.warning(f"Pagination check failed: {e}")

    return all_docs

def run_bb_scraper():
    logger.info("=" * 60)
    logger.info("Bangladesh Bank Scraper — Starting")
    logger.info("=" * 60)

    # Log job start
    job = supabase.table("scraper_jobs").insert({
        "source":     "Bangladesh Bank",
        "started_at": datetime.utcnow().isoformat(),
        "status":     "running",
    }).execute()
    job_id = job.data[0]["id"] if job.data else None

    headers = {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection":      "keep-alive",
    }

    total_found = 0
    total_new   = 0
    all_errors  = []

    # ── Scrape main BB circular page ─────────────────────────
    # All departments appear on the same listing page
    main_url = "https://www.bb.org.bd/en/index.php/mediaroom/circular/brpd"

    try:
        docs = get_all_bb_pages(main_url, headers)
        total_found = len(docs)

        logger.info(f"\nTotal documents extracted: {total_found}")
        logger.info("Saving to database...")

        # Show department breakdown before saving
        from collections import Counter
        dept_counts = Counter(d["department"] for d in docs)
        for dept, count in sorted(dept_counts.items()):
            logger.info(f"  {dept}: {count} circulars")

        logger.info("")

        for doc in docs:
            if save_document(doc):
                total_new += 1
            time.sleep(0.1)  # small delay to avoid overwhelming Supabase

    except Exception as e:
        msg = f"Scraper error: {e}"
        logger.error(msg)
        all_errors.append(msg)

    # ── Update job log ────────────────────────────────────────
    if job_id:
        supabase.table("scraper_jobs").update({
            "completed_at": datetime.utcnow().isoformat(),
            "status":       "completed",
            "docs_found":   total_found,
            "docs_new":     total_new,
            "errors":       all_errors if all_errors else None,
        }).eq("id", job_id).execute()

    logger.info("=" * 60)
    logger.info("Scraper finished!")
    logger.info(f"  Found : {total_found}")
    logger.info(f"  New   : {total_new}")
    logger.info(f"  Errors: {len(all_errors)}")
    logger.info("=" * 60)

    return {"found": total_found, "new": total_new, "errors": len(all_errors)}


if __name__ == "__main__":
    result = run_bb_scraper()
    print(f"\nResult: {result}")