"""
Bangladesh Bank Historical Circular Scraper
============================================
Uses the BB circular search form (POST) to fetch ALL historical circulars
from all 41 departments. No date restriction — gets complete archive.

Key findings from HTML inspection:
- URL: https://www.bb.org.bd/en/index.php/mediaroom/circular
- Method: POST
- Fields: cboDept (dept ID), from_date, to_date, search_circular
- Date format: YYYY-MM-DD
- No date = all records for that department
- Must search one department at a time
"""

import httpx
import re
import time
from bs4 import BeautifulSoup
from datetime import datetime, date
from loguru import logger
from app.database import supabase

BB_SEARCH_URL = "https://www.bb.org.bd/en/index.php/mediaroom/circular"

# All 41 working departments with their IDs and mapped dept codes
BB_DEPARTMENTS = [
    {"id": "1",   "dept": "ABD",   "name": "Accounts & Budgeting Department",          "category": "Banking Operations"},
    {"id": "3",   "dept": "ACD",   "name": "Agricultural Credit Department",            "category": "Agricultural Credit & Finance"},
    {"id": "5",   "dept": "BFIU",  "name": "Bangladesh Financial Intelligence Unit",   "category": "Anti-Money Laundering & CFT"},
    {"id": "85",  "dept": "BRD",   "name": "Bank Resolution Department",               "category": "Banking Operations"},
    {"id": "10",  "dept": "BRPD",  "name": "Banking Regulation and Policy Department", "category": "Credit Policy & Lending"},
    {"id": "106", "dept": "BRPD",  "name": "Banking Regulation and Policy Department", "category": "Credit Policy & Lending"},
    {"id": "69",  "dept": "CGD",   "name": "Credit Guarantee Department",              "category": "Credit Policy & Lending"},
    {"id": "11",  "dept": "CIB",   "name": "Credit Information Bureau",                "category": "Credit Policy & Lending"},
    {"id": "48",  "dept": "DMD",   "name": "Debt Management Department",               "category": "Monetary Policy"},
    {"id": "23",  "dept": "DBI",   "name": "Department of Banking Inspection",         "category": "Banking Operations"},
    {"id": "54",  "dept": "DBI",   "name": "Department of Banking Inspection",         "category": "Banking Operations"},
    {"id": "26",  "dept": "DCM",   "name": "Department of Currency Management",        "category": "Banking Operations"},
    {"id": "2",   "dept": "DFIM",  "name": "Department of Financial Institutions",     "category": "NBFI & Leasing"},
    {"id": "47",  "dept": "DFXI",  "name": "Department of Foreign Exchange Inspection","category": "Foreign Exchange & Remittance"},
    {"id": "20",  "dept": "DOS",   "name": "Department of Off-Site Supervision",       "category": "Banking Operations"},
    {"id": "53",  "dept": "DID",   "name": "Deposit Insurance Department",             "category": "Banking Operations"},
    {"id": "33",  "dept": "EEFU",  "name": "Equity and Entrepreneurship Fund Unit",    "category": "Credit Policy & Lending"},
    {"id": "66",  "dept": "FID",   "name": "Financial Inclusion Department",           "category": "Financial Inclusion"},
    {"id": "58",  "dept": "FICSD", "name": "Financial Integrity & Customer Services",  "category": "Banking Operations"},
    {"id": "14",  "dept": "FSSPD", "name": "Financial Sector Support & Strategic",     "category": "Banking Operations"},
    {"id": "57",  "dept": "FSD",   "name": "Financial Stability Department",           "category": "Banking Operations"},
    {"id": "4",   "dept": "FEID",  "name": "Foreign Exchange Investment Department",   "category": "Foreign Exchange & Remittance"},
    {"id": "49",  "dept": "FEOD",  "name": "Foreign Exchange Operation Department",    "category": "Foreign Exchange & Remittance"},
    {"id": "6",   "dept": "FEPD",  "name": "Foreign Exchange Policy Department",       "category": "Foreign Exchange & Remittance"},
    {"id": "110", "dept": "FEPD",  "name": "Foreign Exchange Policy Department",       "category": "Foreign Exchange & Remittance"},
    {"id": "12",  "dept": "FRTMD", "name": "Forex Reserve & Treasury Management",      "category": "Monetary Policy"},
    {"id": "13",  "dept": "GO",    "name": "Governor Office",                          "category": "Banking Operations"},
    {"id": "64",  "dept": "ISMD",  "name": "Integrated Supervision Management",        "category": "Banking Operations"},
    {"id": "52",  "dept": "IPFF",  "name": "Investment Promotion & Financing Facility","category": "Credit Policy & Lending"},
    {"id": "86",  "dept": "IBRPD", "name": "Islami Banking Regulations and Policy",    "category": "Islamic Banking"},
    {"id": "27",  "dept": "MPD",   "name": "Monetary Policy Department",               "category": "Monetary Policy"},
    {"id": "59",  "dept": "PSD",   "name": "Payment Systems Department",               "category": "Digital Banking & Fintech"},
    {"id": "111", "dept": "PSD",   "name": "Payment Systems Department",               "category": "Digital Banking & Fintech"},
    {"id": "90",  "dept": "PSSD",  "name": "Payment Systems Supervision Department",   "category": "Digital Banking & Fintech"},
    {"id": "71",  "dept": "SME",   "name": "SME Development Project",                  "category": "Credit Policy & Lending"},
    {"id": "30",  "dept": "SD",    "name": "Secretary's Department",                   "category": "Banking Operations"},
    {"id": "51",  "dept": "SME",   "name": "SME & Special Programmes Department",      "category": "Credit Policy & Lending"},
    {"id": "36",  "dept": "STATS", "name": "Statistics Department",                    "category": "Banking Operations"},
    {"id": "104", "dept": "SDAD",  "name": "Supervisory Data Management & Analytics",  "category": "Banking Operations"},
    {"id": "88",  "dept": "SPCD",  "name": "Supervisory Policy and Coordination",      "category": "Banking Operations"},
    {"id": "61",  "dept": "SFD",   "name": "Sustainable Finance Department",           "category": "Green Banking & Sustainable Finance"},
]

TOPIC_KEYWORDS = {
    "loan classification":  ["classification", "provisioning", "NPL", "loan"],
    "AML/CFT":              ["money laundering", "AML", "CFT", "terrorist", "suspicious"],
    "capital adequacy":     ["capital", "CRAR", "Basel", "adequacy"],
    "foreign exchange":     ["foreign exchange", "remittance", "NRB", "export", "import"],
    "digital banking":      ["mobile", "internet banking", "fintech", "MFS", "digital"],
    "KYC":                  ["KYC", "know your customer", "CDD"],
    "SME":                  ["SME", "small enterprise", "medium enterprise"],
    "green banking":        ["green", "sustainable", "ESG", "climate"],
    "Islamic banking":      ["Islamic", "Shariah", "mudaraba", "musharaka"],
    "interest rate":        ["interest rate", "lending rate", "deposit rate"],
    "agricultural credit":  ["agricultural", "crop loan", "kisan", "farm"],
    "monetary policy":      ["monetary policy", "repo", "CRR", "SLR", "bank rate"],
    "payment system":       ["payment", "clearing", "settlement", "RTGS", "BEFTN"],
    "financial inclusion":  ["financial inclusion", "agent banking", "school banking"],
}


def extract_topic_tags(title: str) -> list:
    tags  = []
    lower = title.lower()
    for tag, keywords in TOPIC_KEYWORDS.items():
        if any(kw.lower() in lower for kw in keywords):
            tags.append(tag)
    return tags if tags else ["general"]


def parse_date_bb(date_str: str) -> str:
    """Parse BB date format DD/MM/YY → YYYY-MM-DD"""
    if not date_str:
        return str(date.today())
    date_str = date_str.strip()
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$', date_str)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2:
            y = '20' + y
        try:
            datetime(int(y), int(mo), int(d))
            return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
        except ValueError:
            pass
    return str(date.today())


def split_title_and_ref(raw_title: str, dept_code: str) -> tuple:
    """Split 'BRPD Circular No. 14: Guidelines on...' into (ref, title)"""
    raw_title = raw_title.strip()
    if ':' in raw_title:
        colon = raw_title.index(':')
        before = raw_title[:colon].strip()
        after  = raw_title[colon+1:].strip()
        if len(before) < 80 and len(after) > 3:
            return before, after
    return f"{dept_code} Circular", raw_title


def detect_dept_from_title(title: str, default_dept: str) -> str:
    """Detect actual department code from circular title prefix."""
    DEPT_PREFIX_MAP = {
        'BRPD':    'BRPD',  'DOS':   'DOS',   'DFIM':   'DFIM',
        'FEPD':    'FEPD',  'BFIU':  'BFIU',  'PSD':    'PSD',
        'MPD':     'MPD',   'SME':   'SME',   'SMESPD': 'SME',
        'SDAD':    'SDAD',  'DMD':   'DMD',   'SPCD':   'SPCD',
        'GBCSRD':  'GBCSRD','SFD':   'SFD',   'FEOD':   'FEOD',
        'FEID':    'FEID',  'ACD':   'ACD',   'CIB':    'CIB',
        'FICSD':   'FICSD', 'ISMD':  'ISMD',  'FSD':    'FSD',
        'FININCLD':'FININCLD',
    }
    first = title.strip().split()[0].upper() if title.strip() else ''
    base  = re.sub(r'[-\d]+$', '', first)
    for key, val in DEPT_PREFIX_MAP.items():
        if first == key or base == key or first.startswith(key):
            return val
    return default_dept


def build_url(href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith('http'):
        return href
    if href.startswith('/'):
        return f"https://www.bb.org.bd{href}"
    return f"https://www.bb.org.bd/{href}"


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
        return True
    except Exception as e:
        logger.error(f"  Save failed: {e}")
        return False


def scrape_department(dept: dict, headers: dict, session: httpx.Client) -> list:
    """
    Fetch ALL circulars for one department using POST form.
    No date filter = returns all historical records.
    """
    documents = []
    seen_urls = set()

    try:
        data = {
            'cboDept':         dept["id"],
            'from_date':       '',
            'to_date':         '',
            'search_circular': 'Search',
        }

        r = session.post(
            BB_SEARCH_URL,
            data=data,
            timeout=60,
            follow_redirects=True
        )

        if r.status_code != 200:
            logger.warning(f"  HTTP {r.status_code}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.find_all("tr")

        for row in rows:
            tds = row.find_all("td")
            if len(tds) < 2:
                continue

            # Col 0: Date (DD/MM/YY)
            date_str   = tds[0].get_text(strip=True)
            issue_date = parse_date_bb(date_str)

            # Col 1: Full title (class="text-left")
            raw_title = tds[1].get_text(strip=True)
            if not raw_title or len(raw_title) < 5:
                continue

            # Col 2: English PDF
            en_url = ""
            if len(tds) > 2:
                en_td_text = tds[2].get_text(strip=True).lower()
                if 'not available' not in en_td_text:
                    for a in tds[2].find_all("a"):
                        href = a.get("pdf-link") or a.get("href", "")
                        if href:
                            en_url = build_url(href)
                            break

            # Col 3: Bangla PDF
            bn_url = ""
            if len(tds) > 3:
                bn_td_text = tds[3].get_text(strip=True).lower()
                if 'not available' not in bn_td_text:
                    for a in tds[3].find_all("a"):
                        href = a.get("pdf-link") or a.get("href", "")
                        if href:
                            bn_url = build_url(href)
                            break

            primary_url = en_url or bn_url
            if not primary_url or primary_url in seen_urls:
                continue
            seen_urls.add(primary_url)

            # Split title into ref + subject
            circ_ref, clean_title = split_title_and_ref(raw_title, dept["dept"])

            # Detect actual department from title prefix
            actual_dept = detect_dept_from_title(raw_title, dept["dept"])

            doc = {
                "title_en":         clean_title,
                "title_bn":         None,
                "circular_ref":     circ_ref,
                "issuing_body":     "BB",
                "department":       actual_dept,
                "doc_type":         "Circular",
                "issue_date":       issue_date,
                "status":           "active",
                "primary_url":      primary_url,
                "mirror_url":       bn_url if bn_url and bn_url != primary_url else None,
                "doc_format":       "pdf",
                "language":         "english",
                "category_primary": dept["category"],
                "topic_tags":       extract_topic_tags(clean_title),
                "added_by":         "scraper",
            }
            documents.append(doc)

    except httpx.TimeoutException:
        logger.error(f"  Timeout on dept {dept['id']}")
    except Exception as e:
        logger.error(f"  Error on dept {dept['id']}: {e}")

    return documents


def run_bb_historical_scraper():
    logger.info("=" * 60)
    logger.info("BB Historical Scraper — All Departments, All Years")
    logger.info(f"Total departments to scrape: {len(BB_DEPARTMENTS)}")
    logger.info("=" * 60)

    job = supabase.table("scraper_jobs").insert({
        "source":     "Bangladesh Bank (Historical)",
        "started_at": datetime.utcnow().isoformat(),
        "status":     "running",
    }).execute()
    job_id = job.data[0]["id"] if job.data else None

    headers = {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Content-Type":    "application/x-www-form-urlencoded",
        "Referer":         BB_SEARCH_URL,
    }

    total_found = 0
    total_new   = 0
    all_errors  = []

    # Use a session for connection reuse
    with httpx.Client(headers=headers, follow_redirects=True) as session:
        for i, dept in enumerate(BB_DEPARTMENTS, 1):
            logger.info(f"[{i:2d}/{len(BB_DEPARTMENTS)}] {dept['dept']:8s} — {dept['name'][:40]}")

            try:
                docs = scrape_department(dept, headers, session)
                total_found += len(docs)
                new_count    = 0

                for doc in docs:
                    if save_document(doc):
                        total_new += 1
                        new_count += 1

                logger.info(f"          Found={len(docs):4d} | New={new_count:4d}")

                # Polite delay between departments
                time.sleep(2)

            except Exception as e:
                msg = f"Error on dept {dept['id']} ({dept['dept']}): {e}"
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
    logger.info("BB Historical Scraper — FINISHED!")
    logger.info(f"  Total found : {total_found}")
    logger.info(f"  New saved   : {total_new}")
    logger.info(f"  Errors      : {len(all_errors)}")
    logger.info("=" * 60)

    return {"found": total_found, "new": total_new, "errors": len(all_errors)}


if __name__ == "__main__":
    result = run_bb_historical_scraper()
    print(f"\nFinal Result: {result}")