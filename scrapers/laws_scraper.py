"""
Banking Laws & Acts Scraper
============================
Adds foundational banking laws to the knowledge base.

Sources:
1. Bangladesh laws — bdlaws.minlaw.gov.bd (HTML pages)
2. International standards — manually curated with known URLs
"""

import httpx
import time
from loguru import logger
from datetime import datetime
from app.database import supabase

# ── Bangladesh Banking Laws ───────────────────────────────────
# Source: bdlaws.minlaw.gov.bd
# These are the core laws every banker must know

BD_LAWS = [
    {
        "title_en":     "The Negotiable Instruments Act, 1881",
        "title_bn":     "আলোচ্য দলিল আইন, ১৮৮১",
        "circular_ref": "Act No. XXVI of 1881",
        "url":          "http://bdlaws.minlaw.gov.bd/act-46.html",
        "pdf_url":      "http://bdlaws.minlaw.gov.bd/act-46.html",
        "year":         1881,
        "summary":      "Defines and governs promissory notes, bills of exchange and cheques. Critical for dishonour of cheque cases under Section 138. Governs negotiable instruments in banking transactions.",
        "tags":         ["negotiable instruments", "cheque dishonour", "promissory note", "bill of exchange"],
    },
    {
        "title_en":     "The Limitation Act, 1908",
        "title_bn":     "তামাদি আইন, ১৯০৮",
        "circular_ref": "Act No. IX of 1908",
        "url":          "http://bdlaws.minlaw.gov.bd/act-79.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-04-05-42-44-79.-The-Limitation-Act,-1908.pdf",
        "year":         1908,
        "summary":      "Sets time limits for filing legal suits. Crucial for loan recovery — banks must file within limitation period. Different periods for different types of claims including mortgage suits and money decrees.",
        "tags":         ["limitation period", "loan recovery", "legal proceedings", "time limit"],
    },
    {
        "title_en":     "The Bank Companies Act, 1991",
        "title_bn":     "ব্যাংক কোম্পানী আইন, ১৯৯১",
        "circular_ref": "Act No. XIV of 1991",
        "url":          "http://bdlaws.minlaw.gov.bd/act-765.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-07-11-45-07-765.-The-Bank-Companies-Act,-1991.pdf",
        "year":         1991,
        "summary":      "Primary legislation governing banking companies in Bangladesh. Covers licensing, capital requirements, management, supervision, winding up and all core banking operations. Administered by Bangladesh Bank.",
        "tags":         ["banking regulation", "bank license", "capital requirement", "Bangladesh Bank supervision"],
    },
    {
        "title_en":     "The Financial Institutions Act, 1993",
        "title_bn":     "আর্থিক প্রতিষ্ঠান আইন, ১৯৯৩",
        "circular_ref": "Act No. XXVII of 1993",
        "url":          "http://bdlaws.minlaw.gov.bd/act-796.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-07-11-45-07-796.-The-Financial-Institutions-Act,-1993.pdf",
        "year":         1993,
        "summary":      "Governs non-bank financial institutions (NBFIs) including leasing companies, merchant banks and finance companies. Sets licensing, capital and operational requirements for NBFIs.",
        "tags":         ["NBFI", "financial institution", "leasing", "merchant bank"],
    },
    {
        "title_en":     "The Artha Rin Adalat Ain, 2003 (Money Loan Court Act)",
        "title_bn":     "অর্থ ঋণ আদালত আইন, ২০০৩",
        "circular_ref": "Act No. VIII of 2003",
        "url":          "http://bdlaws.minlaw.gov.bd/act-902.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-07-11-45-07-902.-The-Artha-Rin-Adalat-Ain,-2003.pdf",
        "year":         2003,
        "summary":      "Establishes Money Loan Courts for speedy resolution of loan recovery cases. Covers filing procedures, attachment of assets, auction, settlement and decree execution. Essential for NPL recovery.",
        "tags":         ["loan recovery", "money loan court", "NPL recovery", "Artha Rin", "legal proceedings"],
    },
    {
        "title_en":     "The Bankruptcy Act, 1997",
        "title_bn":     "দেউলিয়া আইন, ১৯৯৭",
        "circular_ref": "Act No. X of 1997",
        "url":          "http://bdlaws.minlaw.gov.bd/act-843.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-07-11-45-07-843.-The-Bankruptcy-Act,-1997.pdf",
        "year":         1997,
        "summary":      "Governs insolvency proceedings for individuals and companies unable to repay debts. Relevant for banks dealing with insolvent borrowers, priority of claims and restructuring.",
        "tags":         ["bankruptcy", "insolvency", "loan recovery", "debt restructuring"],
    },
    {
        "title_en":     "The Foreign Exchange Regulation Act, 1947",
        "title_bn":     "বৈদেশিক মুদ্রা নিয়ন্ত্রণ আইন, ১৯৪৭",
        "circular_ref": "Act No. VII of 1947",
        "url":          "http://bdlaws.minlaw.gov.bd/act-16.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-03-11-45-40-16.-The-Foreign-Exchange-Regulation-Act,-1947.pdf",
        "year":         1947,
        "summary":      "Regulates foreign exchange transactions, remittances, export proceeds and imports. Authorised dealers (banks) operate under this Act. Governs NRB accounts and cross-border transactions.",
        "tags":         ["foreign exchange", "remittance", "NRB", "export proceeds", "authorised dealer"],
    },
    {
        "title_en":     "The Money Laundering Prevention Act, 2012",
        "title_bn":     "মানি লন্ডারিং প্রতিরোধ আইন, ২০১২",
        "circular_ref": "Act No. V of 2012",
        "url":          "http://bdlaws.minlaw.gov.bd/act-1094.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-07-11-45-07-1094.-The-Money-Laundering-Prevention-Act,-2012.pdf",
        "year":         2012,
        "summary":      "Primary AML legislation. Defines money laundering, obligations of reporting organisations (banks), suspicious transaction reporting, penalties and BFIU powers. Mandatory compliance for all banks.",
        "tags":         ["money laundering", "AML", "BFIU", "suspicious transaction", "compliance"],
    },
    {
        "title_en":     "The Anti-Terrorism Act, 2009 (Amendment 2012)",
        "title_bn":     "সন্ত্রাস বিরোধী আইন, ২০০৯",
        "circular_ref": "Act No. XVI of 2009",
        "url":          "http://bdlaws.minlaw.gov.bd/act-1027.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-07-11-45-07-1027.-The-Anti-Terrorism-Act,-2009.pdf",
        "year":         2009,
        "summary":      "Governs prevention of terrorist financing (CFT). Banks must screen transactions and customers against designated lists. Covers freezing of assets and reporting obligations.",
        "tags":         ["terrorist financing", "CFT", "AML", "sanctions", "FATF"],
    },
    {
        "title_en":     "The Contract Act, 1872",
        "title_bn":     "চুক্তি আইন, ১৮৭২",
        "circular_ref": "Act No. IX of 1872",
        "url":          "http://bdlaws.minlaw.gov.bd/act-26.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-03-11-45-40-26.-The-Contract-Act,-1872.pdf",
        "year":         1872,
        "summary":      "Foundation of all banking agreements. Governs loan agreements, guarantees, indemnities and all contracts. Defines offer, acceptance, consideration, void/voidable contracts and remedies for breach.",
        "tags":         ["contract", "loan agreement", "guarantee", "indemnity", "legal"],
    },
    {
        "title_en":     "The Transfer of Property Act, 1882",
        "title_bn":     "সম্পত্তি হস্তান্তর আইন, ১৮৮২",
        "circular_ref": "Act No. IV of 1882",
        "url":          "http://bdlaws.minlaw.gov.bd/act-30.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-03-11-45-40-30.-The-Transfer-of-Property-Act,-1882.pdf",
        "year":         1882,
        "summary":      "Governs mortgage, charge and transfer of immovable property. Critical for banks taking collateral — types of mortgage, rights of mortgagor/mortgagee, foreclosure and sale proceedings.",
        "tags":         ["mortgage", "collateral", "property", "charge", "security"],
    },
    {
        "title_en":     "The Registration Act, 1908",
        "title_bn":     "নিবন্ধন আইন, ১৯০৮",
        "circular_ref": "Act No. XVI of 1908",
        "url":          "http://bdlaws.minlaw.gov.bd/act-79.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-04-05-42-44-79.-The-Limitation-Act,-1908.pdf",
        "year":         1908,
        "summary":      "Governs registration of documents including mortgages, deeds and property transfers. Banks must ensure proper registration of security documents to protect their interests.",
        "tags":         ["registration", "mortgage", "property", "security document"],
    },
    {
        "title_en":     "The Stamp Act, 1899",
        "title_bn":     "স্ট্যাম্প আইন, ১৮৯৯",
        "circular_ref": "Act No. II of 1899",
        "url":          "http://bdlaws.minlaw.gov.bd/act-63.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-03-11-45-40-63.-The-Stamp-Act,-1899.pdf",
        "year":         1899,
        "summary":      "Requires proper stamping of financial instruments including loan agreements, mortgages, guarantees and promissory notes. Improperly stamped instruments are inadmissible as evidence.",
        "tags":         ["stamp duty", "loan agreement", "mortgage", "promissory note", "legal"],
    },
    {
        "title_en":     "The Securities and Exchange Ordinance, 1969",
        "title_bn":     "সিকিউরিটিজ ও বিনিময় অধ্যাদেশ, ১৯৬৯",
        "circular_ref": "Ordinance No. XVII of 1969",
        "url":          "http://bdlaws.minlaw.gov.bd/act-388.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-05-08-37-47-388.-The-Securities-and-Exchange-Ordinance,-1969.pdf",
        "year":         1969,
        "summary":      "Foundation of capital market regulation. Governs securities issuance, trading and BSEC powers. Relevant for banks involved in capital market activities.",
        "tags":         ["securities", "capital market", "BSEC", "stock exchange"],
    },
    {
        "title_en":     "The Companies Act, 1994",
        "title_bn":     "কোম্পানী আইন, ১৯৯৪",
        "circular_ref": "Act No. XVIII of 1994",
        "url":          "http://bdlaws.minlaw.gov.bd/act-802.html",
        "pdf_url":      "http://old.bdlaws.minlaw.gov.bd/upload/bdcodeact/2023-12-07-11-45-07-802.-The-Companies-Act,-1994.pdf",
        "year":         1994,
        "summary":      "Governs formation, management and winding up of companies. Relevant for corporate banking — opening accounts, lending to companies, corporate guarantees and security creation.",
        "tags":         ["corporate", "company law", "winding up", "corporate governance"],
    },
]

# ── International Banking Standards ──────────────────────────
# Manually curated — these are not on bdlaws.gov.bd

INTERNATIONAL_STANDARDS = [
    {
        "title_en":     "UCP 600 — Uniform Customs and Practice for Documentary Credits (2007)",
        "title_bn":     "ইউসিপি ৬০০ — প্রামাণ্যপত্র ঋণের অভিন্ন প্রথা ও চর্চা",
        "circular_ref": "ICC Publication No. 600",
        "url":          "https://www.bb.org.bd/en/index.php/financialactivity/forexguidline",
        "pdf_url":      "https://www.bb.org.bd/en/index.php/financialactivity/forexguidline",
        "year":         2007,
        "summary":      "International rules governing letters of credit (LC). Defines rights and obligations of issuing bank, confirming bank, beneficiary and applicant. Used in all documentary credit transactions. Issued by ICC Paris.",
        "tags":         ["UCP 600", "letter of credit", "LC", "trade finance", "documentary credit", "ICC"],
    },
    {
        "title_en":     "URDG 758 — Uniform Rules for Demand Guarantees (2010)",
        "title_bn":     "ইউআরডিজি ৭৫৮ — চাহিদা গ্যারান্টির অভিন্ন বিধিমালা",
        "circular_ref": "ICC Publication No. 758",
        "url":          "https://iccwbo.org/business-solutions/incoterms-rules/",
        "pdf_url":      "https://iccwbo.org/business-solutions/incoterms-rules/",
        "year":         2010,
        "summary":      "International rules for demand guarantees and counter-guarantees. Governs bank guarantees, performance bonds, advance payment guarantees. Replaces URDG 458. Used in project finance and trade.",
        "tags":         ["bank guarantee", "demand guarantee", "URDG", "performance bond", "trade finance"],
    },
    {
        "title_en":     "Incoterms 2020 — International Commercial Terms",
        "title_bn":     "ইনকোটার্মস ২০২০ — আন্তর্জাতিক বাণিজ্যিক শর্তাবলী",
        "circular_ref": "ICC Incoterms 2020",
        "url":          "https://iccwbo.org/business-solutions/incoterms-rules/",
        "pdf_url":      "https://iccwbo.org/business-solutions/incoterms-rules/",
        "year":         2020,
        "summary":      "Standard trade terms defining delivery obligations, risk transfer and costs between buyer and seller. Used in LC documentation — FOB, CIF, CFR, EXW, DDP etc. Essential for trade finance officers.",
        "tags":         ["Incoterms", "trade finance", "letter of credit", "FOB", "CIF", "export", "import"],
    },
    {
        "title_en":     "Basel III Framework — Capital Adequacy and Liquidity Standards",
        "title_bn":     "ব্যাসেল-III কাঠামো — মূলধন পর্যাপ্ততা ও তারল্য মান",
        "circular_ref": "BCBS Basel III (2010, revised 2017)",
        "url":          "https://www.bis.org/bcbs/basel3.htm",
        "pdf_url":      "https://www.bis.org/bcbs/publ/d424.pdf",
        "year":         2010,
        "summary":      "BIS/BCBS framework for bank capital adequacy, stress testing and liquidity risk. Introduces CET1, Tier 1, Tier 2 capital, LCR, NSFR and leverage ratio. Implemented in Bangladesh through BB RBCA guidelines.",
        "tags":         ["Basel III", "capital adequacy", "CRAR", "LCR", "NSFR", "BIS", "liquidity"],
    },
    {
        "title_en":     "FATF 40 Recommendations — AML/CFT International Standards",
        "title_bn":     "এফএটিএফ ৪০ সুপারিশ — মানি লন্ডারিং ও সন্ত্রাসী অর্থায়ন প্রতিরোধের আন্তর্জাতিক মান",
        "circular_ref": "FATF Recommendations (2012, updated 2023)",
        "url":          "https://www.fatf-gafi.org/en/topics/fatf-recommendations.html",
        "pdf_url":      "https://www.fatf-gafi.org/content/dam/fatf-gafi/recommendations/FATF%20Recommendations%202012.pdf",
        "year":         2012,
        "summary":      "International AML/CFT standards set by FATF. Covers customer due diligence, record keeping, suspicious transaction reporting, correspondent banking, PEPs and sanctions compliance. Bangladesh implements these through AML Act and BB guidelines.",
        "tags":         ["FATF", "AML", "CFT", "KYC", "CDD", "suspicious transaction", "PEP", "sanctions"],
    },
    {
        "title_en":     "URR 725 — Uniform Rules for Bank-to-Bank Reimbursements",
        "title_bn":     "ইউআরআর ৭২৫ — ব্যাংক-থেকে-ব্যাংক প্রতিদান বিধিমালা",
        "circular_ref": "ICC Publication No. 725",
        "url":          "https://iccwbo.org/",
        "pdf_url":      "https://iccwbo.org/",
        "year":         2008,
        "summary":      "Rules governing reimbursement claims between banks under letters of credit. Used when reimbursing bank is separate from issuing bank. Important for correspondent banking and LC operations.",
        "tags":         ["reimbursement", "letter of credit", "correspondent banking", "trade finance"],
    },
    {
        "title_en":     "ISP98 — International Standby Practices",
        "title_bn":     "আইএসপি৯৮ — আন্তর্জাতিক স্ট্যান্ডবাই অনুশীলন",
        "circular_ref": "ICC Publication No. 590",
        "url":          "https://iccwbo.org/",
        "pdf_url":      "https://iccwbo.org/",
        "year":         1998,
        "summary":      "Rules for standby letters of credit as an alternative to UCP 600. Used for payment guarantees, performance standby and financial standby instruments. Alternative framework to URDG 758.",
        "tags":         ["standby LC", "letter of credit", "bank guarantee", "trade finance"],
    },
]


def document_exists(url: str) -> bool:
    result = (
        supabase.table("documents")
        .select("id")
        .eq("primary_url", url)
        .execute()
    )
    return len(result.data) > 0


def save_law(doc: dict) -> bool:
    try:
        if document_exists(doc["primary_url"]):
            logger.info(f"  Already exists: {doc['title_en'][:60]}")
            return False
        supabase.table("documents").insert(doc).execute()
        logger.info(f"  + Saved: {doc['title_en'][:60]}")
        return True
    except Exception as e:
        logger.error(f"  Failed: {e}")
        return False


def run_laws_scraper():
    logger.info("=" * 60)
    logger.info("Banking Laws & Acts Scraper")
    logger.info("=" * 60)

    job = supabase.table("scraper_jobs").insert({
        "source":     "Laws & Acts",
        "started_at": datetime.utcnow().isoformat(),
        "status":     "running",
    }).execute()
    job_id = job.data[0]["id"] if job.data else None

    saved = 0

    # ── Add Bangladesh Laws ───────────────────────────────────
    logger.info(f"\nAdding {len(BD_LAWS)} Bangladesh banking laws...")
    for law in BD_LAWS:
        doc = {
            "title_en":         law["title_en"],
            "title_bn":         law.get("title_bn"),
            "circular_ref":     law["circular_ref"],
            "issuing_body":     "Ministry of Law",
            "department":       "Laws & Acts",
            "doc_type":         "Act",
            "issue_date":       f"{law['year']}-01-01",
            "status":           "active",
            "primary_url":      law.get("pdf_url") or law["url"],
            "mirror_url":       law["url"],
            "doc_format":       "pdf" if ".pdf" in (law.get("pdf_url") or "") else "html",
            "language":         "english",
            "category_primary": "Banking Laws & Acts",
            "topic_tags":       law.get("tags", []),
            "summary_en":       law.get("summary"),
            "added_by":         "scraper",
        }
        if save_law(doc):
            saved += 1
        time.sleep(0.3)

    # ── Add International Standards ───────────────────────────
    logger.info(f"\nAdding {len(INTERNATIONAL_STANDARDS)} international standards...")
    for std in INTERNATIONAL_STANDARDS:
        doc = {
            "title_en":         std["title_en"],
            "title_bn":         std.get("title_bn"),
            "circular_ref":     std["circular_ref"],
            "issuing_body":     "International",
            "department":       "International Standards",
            "doc_type":         "International Standard",
            "issue_date":       f"{std['year']}-01-01",
            "status":           "active",
            "primary_url":      std.get("pdf_url") or std["url"],
            "mirror_url":       std["url"],
            "doc_format":       "pdf" if ".pdf" in (std.get("pdf_url") or "") else "html",
            "language":         "english",
            "category_primary": "International Banking Standards",
            "topic_tags":       std.get("tags", []),
            "summary_en":       std.get("summary"),
            "added_by":         "scraper",
        }
        if save_law(doc):
            saved += 1
        time.sleep(0.3)

    if job_id:
        supabase.table("scraper_jobs").update({
            "completed_at": datetime.utcnow().isoformat(),
            "status":       "completed",
            "docs_found":   len(BD_LAWS) + len(INTERNATIONAL_STANDARDS),
            "docs_new":     saved,
        }).eq("id", job_id).execute()

    logger.info("=" * 60)
    logger.info(f"Laws scraper done! Saved: {saved}")
    logger.info("=" * 60)
    return {"saved": saved}


if __name__ == "__main__":
    result = run_laws_scraper()
    print(f"\nResult: {result}")