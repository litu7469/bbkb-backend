import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from app.database import supabase
from sentence_transformers import SentenceTransformer

TAG_EXPANSIONS = {
    'loan classification':  'loan classification provisioning NPL non-performing classified loans bad debt',
    'provisioning':         'provisioning loan loss reserve specific general provision classified',
    'NPL':                  'NPL non-performing loan classified bad debt doubtful loss',
    'excise duty':          'excise duty bank accounts tax levy charge surcharge government revenue',
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
    'mobile banking':       'mobile financial services MFS bKash Nagad mobile payment wallet',
    'budget':               'budget finance act annual paripatra fiscal year tax rate',
    'single borrower':      'single borrower large loan exposure limit concentration risk',
    'trade finance':        'trade finance letter of credit LC import export guarantee bond',
    'penalty':              'penalty fine enforcement violation sanction suspension',
    'disclosure':           'disclosure price sensitive information reporting transparency',
    'general':              '',
}


def build_doc_text(doc: dict) -> str:
    parts = []

    title = doc.get('title_en') or ''
    if title:
        parts.append(title)
        parts.append(title)

    if doc.get('title_bn'):
        parts.append(doc['title_bn'])

    if doc.get('circular_ref'):
        parts.append(f"Circular reference: {doc['circular_ref']}")

    body = doc.get('issuing_body') or ''
    dept = doc.get('department') or ''
    if body and dept:
        parts.append(f"Issued by {body} {dept} department")
    elif body:
        parts.append(f"Issued by {body}")

    if doc.get('category_primary'):
        parts.append(f"Category: {doc['category_primary']}")

    tags = doc.get('topic_tags') or []
    if tags:
        parts.append(f"Topics: {', '.join(tags)}")
        for tag in tags:
            expansion = TAG_EXPANSIONS.get(tag, '')
            if expansion:
                parts.append(expansion)

    if doc.get('summary_en'):
        parts.append(doc['summary_en'][:800])

    return ' | '.join(parts)


def reembed_missing():
    logger.info("=" * 60)
    logger.info("Re-embedding documents without embeddings")
    logger.info("=" * 60)

    # Load model
    logger.info("Loading embedding model...")
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    logger.info("Model ready!")

    # Get all document IDs
    logger.info("Fetching all document IDs...")
    all_ids = set()
    offset  = 0
    while True:
        r = supabase.table("documents").select("id").range(offset, offset + 999).execute()
        if not r.data:
            break
        for row in r.data:
            all_ids.add(row['id'])
        if len(r.data) < 1000:
            break
        offset += 1000
    logger.info(f"Total documents: {len(all_ids)}")

    # Get already embedded IDs
    logger.info("Fetching existing embedding IDs...")
    embedded_ids = set()
    offset = 0
    while True:
        r = supabase.table("document_chunks").select("document_id").range(offset, offset + 999).execute()
        if not r.data:
            break
        for row in r.data:
            embedded_ids.add(row['document_id'])
        if len(r.data) < 1000:
            break
        offset += 1000
    logger.info(f"Already embedded: {len(embedded_ids)}")

    # Find missing
    missing_ids = list(all_ids - embedded_ids)
    logger.info(f"Missing embeddings: {len(missing_ids)}")

    if not missing_ids:
        logger.info("Nothing to do — all documents already embedded!")
        return

    # Fetch full data for missing docs in batches of 100
    logger.info("Fetching document data...")
    to_process = []
    for i in range(0, len(missing_ids), 100):
        batch_ids = missing_ids[i:i + 100]
        r = (
            supabase.table("documents")
            .select(
                "id, title_en, title_bn, circular_ref, department, "
                "issuing_body, category_primary, topic_tags, summary_en"
            )
            .in_("id", batch_ids)
            .execute()
        )
        if r.data:
            to_process.extend(r.data)

    logger.info(f"Documents to embed: {len(to_process)}")

    # Embed in batches of 50
    saved      = 0
    failed     = 0
    batch_size = 50
    total      = len(to_process)
    total_batches = (total + batch_size - 1) // batch_size

    for i in range(0, total, batch_size):
        batch     = to_process[i:i + batch_size]
        batch_num = i // batch_size + 1
        texts     = [build_doc_text(doc) for doc in batch]

        logger.info(
            f"Batch {batch_num}/{total_batches} "
            f"({i+1}-{min(i+batch_size, total)} of {total})"
        )

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

        for doc, text, emb in zip(batch, texts, embeddings):
            try:
                supabase.table("document_chunks").insert({
                    "document_id": doc['id'],
                    "chunk_index": 0,
                    "chunk_text":  text[:2000],
                    "embedding":   emb.tolist(),
                }).execute()
                saved += 1
            except Exception as e:
                logger.error(f"  Failed: {doc.get('title_en','')[:40]} — {e}")
                failed += 1

        logger.info(f"  Progress: saved={saved} failed={failed}")

    logger.info("=" * 60)
    logger.info(f"Done! Saved={saved} Failed={failed}")
    logger.info("=" * 60)


if __name__ == "__main__":
    reembed_missing()