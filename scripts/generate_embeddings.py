import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from loguru import logger
from app.database import supabase

TAG_EXPANSIONS = {
    'loan classification':  'loan classification provisioning NPL non-performing classified loans bad debt',
    'AML/CFT':              'anti money laundering combating financing terrorism suspicious transaction STR',
    'capital adequacy':     'capital adequacy Basel CRAR regulatory capital requirement Tier-1 Tier-2',
    'foreign exchange':     'foreign exchange remittance NRB export import forex currency',
    'digital banking':      'mobile banking fintech MFS agent banking digital payment internet banking',
    'KYC':                  'know your customer KYC customer due diligence CDD identity verification',
    'SME':                  'small medium enterprise SME loan credit cottage micro',
    'green banking':        'green finance sustainable ESG environment climate carbon',
    'Islamic banking':      'Islamic Shariah mudaraba musharaka halal finance profit sharing',
    'interest rate':        'interest rate lending rate deposit rate spread bank rate',
    'agricultural credit':  'agricultural crop loan rural kisan farm credit seasonal',
    'monetary policy':      'monetary policy repo rate CRR SLR bank rate inflation reserve',
    'payment system':       'payment clearing settlement RTGS BEFTN EFT interbank transfer',
    'financial inclusion':  'financial inclusion unbanked rural banking access school banking agent',
    'withholding tax':      'withholding tax TDS tax deduction at source income tax certificate',
    'VAT':                  'value added tax VAT mushak supplementary duty registration',
    'customs':              'customs duty import export tariff HS code clearance freight',
    'excise duty':          'excise duty bank accounts tax levy charge surcharge government revenue',
    'provisioning':         'provisioning loan loss reserve specific general provision classified',
    'mobile banking':       'mobile financial services MFS bKash Nagad mobile payment wallet',
    'budget':               'budget finance act annual paripatra fiscal year tax rate',
    'SRO':                  'statutory regulatory order gazette notification amendment rule',
    'amendment':            'amendment modification revised updated change circular',
    'penalty':              'penalty fine enforcement violation sanction suspension cancellation',
    'disclosure':           'disclosure price sensitive information reporting transparency',
    'IPO':                  'IPO initial public offering public issue prospectus subscription',
    'stock exchange':       'stock exchange DSE CSE listing trading shares securities',
    'margin loan':          'margin loan leveraged trading securities broker dealer',
    'corporate governance': 'corporate governance board director audit committee AGM EGM',
    'suspicious transaction': 'suspicious transaction report STR monitoring unusual activity',
    'cash transaction':     'cash transaction report CTR threshold large amount',
    'sanctions':            'sanctions blacklist UNSCR FATF designated entity',
    'single borrower':      'single borrower large loan exposure limit concentration risk',
    'trade finance':        'trade finance letter of credit LC import export guarantee bond',
}


def get_model():
    logger.info("Loading embedding model...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    logger.info("Model loaded!")
    return model


def build_doc_text(doc: dict) -> str:
    """
    Build rich searchable text for embedding.
    Repeat title for emphasis, expand topic tags into natural language.
    """
    parts = []

    # Title × 2 (most important signal — doubled for emphasis)
    title = doc.get('title_en') or ''
    if title:
        parts.append(title)
        parts.append(title)

    # Bangla title
    if doc.get('title_bn'):
        parts.append(doc['title_bn'])

    # Circular reference
    if doc.get('circular_ref'):
        parts.append(f"Circular reference: {doc['circular_ref']}")

    # Issuing body + department
    body = doc.get('issuing_body') or ''
    dept = doc.get('department') or ''
    if body and dept:
        parts.append(f"Issued by {body} {dept} department")
    elif body:
        parts.append(f"Issued by {body}")

    # Category
    if doc.get('category_primary'):
        parts.append(f"Category: {doc['category_primary']}")

    # Topic tags — both raw and expanded
    tags = doc.get('topic_tags') or []
    if tags:
        parts.append(f"Topics: {', '.join(tags)}")
        for tag in tags:
            if tag in TAG_EXPANSIONS:
                parts.append(TAG_EXPANSIONS[tag])

    # Summary
    if doc.get('summary_en'):
        parts.append(doc['summary_en'][:800])

    return ' | '.join(parts)


def fetch_all_documents() -> list:
    all_docs  = []
    page_size = 1000
    offset    = 0
    while True:
        result = (
            supabase.table("documents")
            .select(
                "id, title_en, title_bn, circular_ref, department, "
                "issuing_body, category_primary, topic_tags, summary_en"
            )
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = result.data or []
        if not batch:
            break
        all_docs.extend(batch)
        logger.info(f"  Fetched {len(all_docs)} documents...")
        if len(batch) < page_size:
            break
        offset += page_size
    return all_docs


def fetch_embedded_ids() -> set:
    embedded  = set()
    page_size = 1000
    offset    = 0
    while True:
        result = (
            supabase.table("document_chunks")
            .select("document_id")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = result.data or []
        if not batch:
            break
        for row in batch:
            embedded.add(row["document_id"])
        if len(batch) < page_size:
            break
        offset += page_size
    logger.info(f"  Found {len(embedded)} existing embeddings")
    return embedded


def save_embedding(doc_id: str, text: str, embedding: list) -> bool:
    try:
        supabase.table("document_chunks").insert({
            "document_id": doc_id,
            "chunk_index": 0,
            "chunk_text":  text[:2000],
            "embedding":   embedding,
        }).execute()
        return True
    except Exception as e:
        logger.error(f"  Save failed: {e}")
        return False


def run(batch_size: int = 50, skip_existing: bool = True):
    logger.info("=" * 60)
    logger.info("Embedding Generation — Rich Text Version")
    logger.info("=" * 60)

    model    = get_model()
    all_docs = fetch_all_documents()
    logger.info(f"Total documents: {len(all_docs)}")

    if skip_existing:
        embedded_ids = fetch_embedded_ids()
        to_process   = [d for d in all_docs if d['id'] not in embedded_ids]
        logger.info(f"To process: {len(to_process)} (skipping {len(all_docs)-len(to_process)} existing)")
    else:
        to_process = all_docs
        logger.info(f"To process: {len(to_process)} (regenerating all)")

    if not to_process:
        logger.info("All documents already have embeddings!")
        return

    total         = len(to_process)
    saved         = 0
    failed        = 0
    start         = time.time()
    total_batches = (total + batch_size - 1) // batch_size

    for i in range(0, total, batch_size):
        batch     = to_process[i:i + batch_size]
        batch_num = i // batch_size + 1

        logger.info(
            f"Batch {batch_num}/{total_batches} "
            f"({i+1}-{min(i+batch_size, total)} of {total})"
        )

        texts = [build_doc_text(doc) for doc in batch]

        try:
            embeddings = model.encode(
                texts,
                normalize_embeddings=True,
                batch_size=32,
                show_progress_bar=False,
            )
        except Exception as e:
            logger.error(f"  Encoding failed: {e}")
            failed += len(batch)
            continue

        for doc, text, embedding in zip(batch, texts, embeddings):
            if save_embedding(doc['id'], text, embedding.tolist()):
                saved += 1
            else:
                failed += 1

        elapsed   = time.time() - start
        rate      = saved / elapsed if elapsed > 0 else 0
        remaining = (total - i - len(batch)) / rate if rate > 0 else 0

        logger.info(
            f"  Saved={saved} Failed={failed} "
            f"Rate={rate:.1f}/s ETA={remaining:.0f}s"
        )
        time.sleep(0.3)

    elapsed = time.time() - start
    logger.info("=" * 60)
    logger.info("Done!")
    logger.info(f"  Saved : {saved}")
    logger.info(f"  Failed: {failed}")
    logger.info(f"  Time  : {elapsed:.0f}s ({elapsed/60:.1f} min)")
    logger.info("=" * 60)


if __name__ == "__main__":
    run(batch_size=50, skip_existing=False)  # False = regenerate all