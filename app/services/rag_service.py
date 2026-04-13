"""
RAG Service — Bilingual Semantic Search Pipeline
=================================================
For every query:
1. Detect language (English or Bangla)
2. Expand query with related terms in same language
3. Translate query to other language for cross-lingual search
4. Search in BOTH languages simultaneously
5. Keyword boost for exact title matches
6. Merge, deduplicate, rank results
7. Build rich context and generate AI answer with disclaimer
"""

import httpx
import time
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import settings
from app.database import supabase

# ── Global model instance (loaded once) ──────────────────────
_model = None

# ── System Prompts ────────────────────────────────────────────

SYSTEM_PROMPT_EN = """You are an expert Bangladesh banking regulatory assistant with deep knowledge of Bangladesh Bank circulars, NBR tax regulations, BSEC securities laws, and BFIU anti-money laundering guidelines.

Your role is to help compliance officers, bankers, and financial professionals understand regulatory requirements accurately.

STRICT RULES:
1. Answer ONLY using the provided regulatory documents. Do not use general knowledge.
2. Always cite specific circular reference numbers and issuing authority for each key point.
3. Structure your answer clearly with numbered points where applicable.
4. If documents lack sufficient information say: "The provided documents do not contain sufficient information on this specific query. Please refer directly to the cited documents or contact the relevant regulatory authority."
5. If multiple circulars exist on same topic, identify the most recent/current one.
6. Note if any cited circular has been superseded by a newer one.
7. Always respond in English when the question is in English.

You MUST end every response with this disclaimer:
"⚠️ REGULATORY DISCLAIMER: This response is for informational purposes only and does not constitute legal advice. Regulations change frequently — always verify with the latest circular from the issuing authority. For compliance decisions, consult qualified legal counsel or contact Bangladesh Bank directly at www.bb.org.bd"
"""

SYSTEM_PROMPT_BN = """আপনি বাংলাদেশ ব্যাংকিং নিয়ন্ত্রণ বিষয়ক একজন বিশেষজ্ঞ সহকারী। আপনার কাছে বাংলাদেশ ব্যাংকের সার্কুলার, এনবিআর কর বিধিমালা, বিএসইসি সিকিউরিটিজ আইন এবং বিএফআইইউ নির্দেশিকার গভীর জ্ঞান রয়েছে।

কঠোর নিয়মাবলী:
১. শুধুমাত্র নিচে প্রদত্ত নিয়ন্ত্রক দলিলের ভিত্তিতে উত্তর দিন।
২. প্রতিটি গুরুত্বপূর্ণ তথ্যের জন্য নির্দিষ্ট সার্কুলার রেফারেন্স নম্বর ও ইস্যুকারী কর্তৃপক্ষ উল্লেখ করুন।
৩. উত্তর স্পষ্টভাবে ক্রমিক পয়েন্টে সাজান।
৪. দলিলে পর্যাপ্ত তথ্য না থাকলে বলুন: "প্রদত্ত দলিলে এই বিষয়ে পর্যাপ্ত তথ্য নেই। সরাসরি উদ্ধৃত দলিল দেখুন বা সংশ্লিষ্ট কর্তৃপক্ষের সাথে যোগাযোগ করুন।"
৫. পুরানো সার্কুলার উল্লেখ করলে বর্তমান কার্যকর সার্কুলার নির্দেশ করুন।
৬. বাংলায় প্রশ্ন হলে বাংলায় উত্তর দিন।

আপনার উত্তরের শেষে সর্বদা এই দাবিত্যাগ যোগ করুন:
"⚠️ নিয়ন্ত্রক দাবিত্যাগ: এই প্রতিক্রিয়া শুধুমাত্র তথ্যগত উদ্দেশ্যে এবং এটি আইনি পরামর্শ নয়। বিধিমালা প্রায়ই পরিবর্তিত হয় — সর্বদা ইস্যুকারী কর্তৃপক্ষের সর্বশেষ সার্কুলার দিয়ে যাচাই করুন। কমপ্লায়েন্স সিদ্ধান্তের জন্য যোগ্য আইনি পরামর্শদাতার সাথে পরামর্শ করুন বা বাংলাদেশ ব্যাংকের ওয়েবসাইট www.bb.org.bd দেখুন।"
"""

DISCLAIMER_EN = (
    "⚠️ REGULATORY DISCLAIMER: This response is for informational purposes only "
    "and does not constitute legal advice. Regulations change frequently — always "
    "verify with the latest circular from the issuing authority. For compliance "
    "decisions, consult qualified legal counsel or contact Bangladesh Bank at www.bb.org.bd"
)

DISCLAIMER_BN = (
    "⚠️ নিয়ন্ত্রক দাবিত্যাগ: এই প্রতিক্রিয়া শুধুমাত্র তথ্যগত উদ্দেশ্যে এবং "
    "এটি আইনি পরামর্শ নয়। বিধিমালা প্রায়ই পরিবর্তিত হয় — সর্বদা ইস্যুকারী "
    "কর্তৃপক্ষের সর্বশেষ সার্কুলার দিয়ে যাচাই করুন।"
)

# ── Query Expansion Maps ──────────────────────────────────────

EN_EXPANSIONS = {
    'excise duty':          'excise duty bank accounts levy surcharge tax charge government',
    'loan classification':  'loan classification provisioning NPL non-performing classified bad debt',
    'provisioning':         'provisioning loan loss reserve classified specific general provision',
    'npl':                  'NPL non-performing loan classified bad debt substandard doubtful loss',
    'aml':                  'anti money laundering AML CFT suspicious transaction STR reporting',
    'kyc':                  'know your customer KYC customer due diligence CDD identity verification',
    'capital adequacy':     'capital adequacy CRAR Basel regulatory capital Tier-1 Tier-2 requirement',
    'basel':                'Basel capital adequacy CRAR regulatory capital framework risk weighted',
    'mobile banking':       'mobile banking MFS mobile financial services bKash Nagad digital wallet',
    'agent banking':        'agent banking financial inclusion rural banking correspondent',
    'mfs':                  'mobile financial services MFS mobile banking digital payment wallet',
    'single borrower':      'single borrower exposure limit large loan concentration risk',
    'nrb account':          'NRB account non-resident Bangladeshi foreign remittance expatriate',
    'forex':                'foreign exchange forex remittance currency export import NRB',
    'foreign exchange':     'foreign exchange forex remittance currency NRB export import LC',
    'repo':                 'repo rate monetary policy interest rate bank rate CRR SLR',
    'cib':                  'credit information bureau CIB credit report borrower information',
    'sme':                  'SME small medium enterprise loan credit cottage micro industry',
    'green':                'green finance sustainable ESG climate environment carbon emission',
    'islamic':              'Islamic banking Shariah mudaraba musharaka profit sharing halal',
    'letter of credit':     'letter of credit LC trade finance import export guarantee',
    'remittance':           'remittance foreign exchange NRB inward outward expatriate',
    'ipo':                  'IPO initial public offering public issue securities subscription',
    'margin loan':          'margin loan securities broker dealer trading leveraged',
    'insider trading':      'insider trading price sensitive disclosure securities market',
    'rescheduling':         'rescheduling restructuring loan defaulter recovery write-off',
    'interest rate':        'interest rate lending deposit spread SMART base rate',
    'digital bank':         'digital bank branchless internet banking fintech neo-bank',
    'payment system':       'payment system RTGS BEFTN clearing settlement interbank',
    'financial inclusion':  'financial inclusion agent banking school banking unbanked rural',
    'agricultural':         'agricultural credit crop loan rural kisan farm seasonal harvest',
    'trade finance':        'trade finance letter of credit LC export import guarantee bond',
    'corporate governance': 'corporate governance board director audit committee AGM EGM',
    'money laundering':     'money laundering AML CFT suspicious transaction terrorist financing',
    'sanctions':            'sanctions blacklist UNSCR FATF designated entity frozen assets',
}

BN_EXPANSIONS = {
    'ঋণ শ্রেণীবিন্যাস':   'ঋণ শ্রেণীবিন্যাস মন্দ ঋণ খেলাপি loan classification provisioning NPL',
    'প্রভিশনিং':          'প্রভিশনিং সঞ্চিতি ঋণ শ্রেণীবিন্যাস provisioning loan loss reserve',
    'মূলধন পর্যাপ্ততা':   'মূলধন পর্যাপ্ততা ব্যাসেল CRAR capital adequacy Basel regulatory capital',
    'মোবাইল ব্যাংকিং':    'মোবাইল ব্যাংকিং এমএফএস বিকাশ নগদ mobile banking MFS financial services',
    'বৈদেশিক মুদ্রা':     'বৈদেশিক মুদ্রা রেমিট্যান্স এনআরবি foreign exchange remittance NRB',
    'রেমিট্যান্স':         'রেমিট্যান্স বৈদেশিক মুদ্রা প্রবাসী remittance foreign exchange NRB',
    'সন্দেহজনক লেনদেন':   'সন্দেহজনক লেনদেন এসটিআর মানি লন্ডারিং suspicious transaction STR AML',
    'মানি লন্ডারিং':      'মানি লন্ডারিং সন্দেহজনক লেনদেন বিএফআইইউ money laundering AML BFIU',
    'এনআরবি':             'এনআরবি প্রবাসী বাংলাদেশী অ্যাকাউন্ট NRB non-resident Bangladeshi account',
    'সুদের হার':           'সুদের হার আমানত ঋণ ব্যাংক রেট interest rate lending deposit bank rate',
    'ঋণ পুনঃতফসিল':       'ঋণ পুনঃতফসিল পুনর্গঠন খেলাপি rescheduling restructuring defaulter',
    'একক ঋণগ্রহীতা':      'একক ঋণগ্রহীতা সীমা বড় ঋণ single borrower exposure limit large loan',
    'কৃষি ঋণ':            'কৃষি ঋণ গ্রামীণ ফসল agricultural credit crop loan rural seasonal',
    'ইসলামী ব্যাংকিং':    'ইসলামী ব্যাংকিং শরীয়াহ মুদারাবা মুশারাকা Islamic Shariah mudaraba',
    'আবগারি শুল্ক':        'আবগারি শুল্ক ব্যাংক হিসাব কর excise duty bank accounts levy tax',
    'কেওয়াইসি':           'কেওয়াইসি গ্রাহক পরিচিতি যাচাই KYC customer due diligence verification',
    'এজেন্ট ব্যাংকিং':    'এজেন্ট ব্যাংকিং আর্থিক অন্তর্ভুক্তি গ্রামীণ agent banking financial inclusion',
    'মূসক':               'মূসক মূল্য সংযোজন কর VAT value added tax mushak supplementary duty',
    'আয়কর':              'আয়কর পরিপত্র উৎসে কর income tax TDS withholding paripatra',
    'কাস্টমস':            'কাস্টমস আমদানি রপ্তানি শুল্ক customs duty import export tariff',
    'শেয়ার বাজার':        'শেয়ার বাজার পুঁজিবাজার ডিএসই সিএসই stock exchange DSE CSE securities',
    'ডিজিটাল ব্যাংক':     'ডিজিটাল ব্যাংক অনলাইন ইন্টারনেট ব্যাংকিং digital bank branchless fintech',
}

EN_TO_BN_TERMS = {
    'loan classification':  'ঋণ শ্রেণীবিন্যাস',
    'provisioning':         'প্রভিশনিং সঞ্চিতি',
    'excise duty':          'আবগারি শুল্ক',
    'capital adequacy':     'মূলধন পর্যাপ্ততা',
    'mobile banking':       'মোবাইল ব্যাংকিং',
    'money laundering':     'মানি লন্ডারিং',
    'remittance':           'রেমিট্যান্স',
    'foreign exchange':     'বৈদেশিক মুদ্রা',
    'interest rate':        'সুদের হার',
    'single borrower':      'একক ঋণগ্রহীতা',
    'agricultural credit':  'কৃষি ঋণ',
    'agent banking':        'এজেন্ট ব্যাংকিং',
    'KYC':                  'কেওয়াইসি গ্রাহক পরিচিতি',
    'VAT':                  'মূসক মূল্য সংযোজন কর',
    'income tax':           'আয়কর',
    'customs':              'কাস্টমস শুল্ক',
    'Islamic banking':      'ইসলামী ব্যাংকিং শরীয়াহ',
    'rescheduling':         'ঋণ পুনঃতফসিল পুনর্গঠন',
    'digital bank':         'ডিজিটাল ব্যাংক',
    'IPO':                  'আইপিও প্রাথমিক গণপ্রস্তাব',
    'stock exchange':       'শেয়ার বাজার পুঁজিবাজার',
}

BN_TO_EN_TERMS = {
    'ঋণ শ্রেণীবিন্যাস': 'loan classification provisioning',
    'প্রভিশনিং':        'provisioning loan loss',
    'মূলধন পর্যাপ্ততা': 'capital adequacy Basel CRAR',
    'মোবাইল ব্যাংকিং':  'mobile banking MFS',
    'মানি লন্ডারিং':    'money laundering AML CFT',
    'রেমিট্যান্স':       'remittance foreign exchange NRB',
    'বৈদেশিক মুদ্রা':   'foreign exchange forex',
    'সুদের হার':         'interest rate lending rate',
    'একক ঋণগ্রহীতা':    'single borrower exposure limit',
    'কৃষি ঋণ':          'agricultural credit crop loan',
    'এজেন্ট ব্যাংকিং':  'agent banking financial inclusion',
    'আবগারি শুল্ক':      'excise duty bank accounts',
    'মূসক':             'VAT value added tax mushak',
    'আয়কর':            'income tax TDS withholding',
    'কাস্টমস':          'customs duty import export',
    'ইসলামী ব্যাংকিং':  'Islamic banking Shariah',
    'ডিজিটাল ব্যাংক':   'digital bank branchless fintech',
    'শেয়ার বাজার':      'stock exchange DSE CSE securities',
}


# ── Language Detection ────────────────────────────────────────

def detect_language(text: str) -> str:
    bangla_chars = sum(1 for c in text if '\u0980' <= c <= '\u09FF')
    total_chars  = len([c for c in text if c.strip()])
    if total_chars == 0:
        return 'en'
    return 'bn' if (bangla_chars / total_chars) > 0.15 else 'en'


# ── Query Expansion ───────────────────────────────────────────

def expand_query_en(query: str) -> str:
    query_lower = query.lower()
    expansions  = []
    for key, expansion in EN_EXPANSIONS.items():
        if key.lower() in query_lower:
            expansions.append(expansion)
    if expansions:
        expanded = query + ' | ' + ' | '.join(expansions)
        logger.info(f"  EN expansion: {expanded[:100]}")
        return expanded
    return query


def expand_query_bn(query: str) -> str:
    expansions = []
    for key, expansion in BN_EXPANSIONS.items():
        if key in query:
            expansions.append(expansion)
    if expansions:
        expanded = query + ' | ' + ' | '.join(expansions)
        logger.info(f"  BN expansion: {expanded[:100]}")
        return expanded
    return query


def translate_query(query: str, source_lang: str) -> str:
    if source_lang == 'en':
        additions   = []
        query_lower = query.lower()
        for en_term, bn_term in EN_TO_BN_TERMS.items():
            if en_term.lower() in query_lower:
                additions.append(bn_term)
        if additions:
            translated = ' '.join(additions)
            logger.info(f"  Cross-lingual (EN→BN): {translated[:80]}")
            return translated
    else:
        additions = []
        for bn_term, en_term in BN_TO_EN_TERMS.items():
            if bn_term in query:
                additions.append(en_term)
        if additions:
            translated = ' '.join(additions)
            logger.info(f"  Cross-lingual (BN→EN): {translated[:80]}")
            return translated
    return ""


# ── Embedding Model ───────────────────────────────────────────

def get_model():
    global _model
    if _model is None:
        logger.info("Loading embedding model...")
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        logger.info("Embedding model ready!")
    return _model


def embed_query(query: str) -> list:
    model     = get_model()
    embedding = model.encode(query, normalize_embeddings=True)
    return embedding.tolist()


# ── Semantic Search ───────────────────────────────────────────

def search_with_embedding(
    embedding: list,
    limit:     int   = 10,
    threshold: float = 0.30,
) -> list:
    try:
        result = supabase.rpc(
            'semantic_search',
            {
                'query_embedding':      embedding,
                'match_count':          limit,
                'similarity_threshold': threshold,
                'filter_issuing_body':  None,
                'filter_department':    None,
                'filter_date_from':     None,
                'filter_date_to':       None,
            }
        ).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"  Vector search error: {e}")
        return []


def get_keyword_boost(query: str, existing_ids: set, limit: int = 3) -> list:
    """
    Find documents with exact multi-word phrase matches in title.
    Only uses phrases of 2+ meaningful words to avoid false positives.
    """
    results = []
    seen    = set(existing_ids)
    phrases = extract_key_phrases(query)

    # Only use multi-word phrases (2+ words, 8+ chars) to avoid loose matches
    good_phrases = [
        p for p in phrases
        if len(p.split()) >= 2 and len(p) >= 8
    ]

    # Add full query if short and specific
    if len(query.split()) <= 5 and query not in good_phrases:
        good_phrases.insert(0, query)

    for phrase in good_phrases[:3]:
        try:
            docs = (
                supabase.table("documents")
                .select(
                    "id, title_en, title_bn, circular_ref, issuing_body, "
                    "issue_date, primary_url, status, summary_en, department, language"
                )
                .or_(
                    f"title_en.ilike.%{phrase}%,"
                    f"title_bn.ilike.%{phrase}%"
                )
                .eq("status", "active")
                .order("issue_date", desc=True)
                .limit(2)
                .execute()
            )
            if docs.data:
                for doc in docs.data:
                    if doc['id'] not in seen:
                        seen.add(doc['id'])
                        doc['similarity'] = 0.90
                        doc['_boosted']   = True
                        results.append(doc)
        except Exception as e:
            logger.error(f"  Keyword boost error for '{phrase}': {e}")

    return results[:limit]


def get_relevant_documents_semantic(
    query:      str,
    limit:      int = 6,
    query_lang: str = None,
) -> list:
    """
    Bilingual semantic search pipeline:
    1. Expand query in detected language
    2. Translate to other language
    3. Search with both embeddings at adaptive threshold
    4. Add keyword boost for exact title matches
    5. Deduplicate and rank by similarity
    6. Fall back to keyword search if needed
    """
    try:
        lang = query_lang or detect_language(query)
        logger.info(f"  Query language: {lang}")

        # Step 1: Expand in original language
        expanded_query = expand_query_en(query) if lang == 'en' else expand_query_bn(query)

        # Step 2: Translate to other language
        cross_lingual_query = translate_query(query, lang)

        # Step 3: Generate embeddings
        primary_emb    = embed_query(expanded_query)
        cross_lang_emb = embed_query(cross_lingual_query) if cross_lingual_query else None

        # Step 4: Adaptive threshold search
        all_results = []
        seen_ids    = set()

        for threshold in [0.40, 0.30, 0.22]:
            primary_results = search_with_embedding(primary_emb, limit * 2, threshold)
            logger.info(f"  Primary search: {len(primary_results)} docs at threshold={threshold}")

            cross_results = []
            if cross_lang_emb:
                cross_results = search_with_embedding(cross_lang_emb, limit, threshold)
                logger.info(f"  Cross-lingual:  {len(cross_results)} docs at threshold={threshold}")

            for doc in primary_results + cross_results:
                doc_id = doc.get('id') or doc.get('document_id')
                if doc_id and doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    all_results.append(doc)

            if len(all_results) >= 2:
                logger.info(f"  Total unique docs: {len(all_results)} at threshold={threshold}")
                break

            logger.info(f"  Only {len(all_results)} docs, relaxing threshold...")

        # Step 5: Keyword boost for exact title matches
        keyword_boost = get_keyword_boost(query, seen_ids, limit=3)
        if keyword_boost:
            logger.info(f"  Keyword boost added {len(keyword_boost)} docs")

        # Step 6: Merge — boosted docs first, then semantic by score
        final_results = []
        final_seen    = set()

        for doc in keyword_boost + all_results:
            doc_id = doc.get('id') or doc.get('document_id')
            if doc_id and doc_id not in final_seen:
                final_seen.add(doc_id)
                final_results.append(doc)

        # Sort by similarity score descending
        final_results.sort(key=lambda x: x.get('similarity', 0), reverse=True)

        if final_results:
            top = final_results[0].get('similarity', 0)
            logger.info(f"  Final: {len(final_results)} docs, top score: {top:.3f}")
            return final_results[:limit]

        # Keyword fallback
        logger.info("  Falling back to keyword search")
        return get_relevant_documents_keyword(query, limit)

    except Exception as e:
        logger.warning(f"  Semantic search failed: {e}")
        return get_relevant_documents_keyword(query, limit)


def get_relevant_documents_keyword(query: str, limit: int = 6) -> list:
    results  = []
    seen_ids = set()
    phrases  = extract_key_phrases(query)

    for phrase in phrases[:5]:
        if len(phrase) < 3:
            continue
        try:
            docs = (
                supabase.table("documents")
                .select(
                    "id, title_en, title_bn, circular_ref, issuing_body, "
                    "issue_date, primary_url, status, summary_en, department, language"
                )
                .or_(
                    f"title_en.ilike.%{phrase}%,"
                    f"circular_ref.ilike.%{phrase}%,"
                    f"summary_en.ilike.%{phrase}%,"
                    f"title_bn.ilike.%{phrase}%"
                )
                .eq("status", "active")
                .order("issue_date", desc=True)
                .limit(5)
                .execute()
            )
            if docs.data:
                for doc in docs.data:
                    if doc["id"] not in seen_ids:
                        seen_ids.add(doc["id"])
                        results.append(doc)
        except Exception as e:
            logger.error(f"  Keyword search error: {e}")

    return results[:limit]


def extract_key_phrases(query: str) -> list:
    stop_words = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
        'have', 'has', 'do', 'does', 'will', 'would', 'could', 'should',
        'what', 'how', 'when', 'where', 'why', 'which', 'who', 'for',
        'on', 'in', 'at', 'to', 'of', 'and', 'or', 'but', 'with', 'by',
        'কি', 'কী', 'কেন', 'কিভাবে', 'এবং', 'এর', 'এই', 'সেই', 'কত',
    }
    phrases    = [query.strip()]
    words      = query.split()
    meaningful = [w for w in words if w.lower() not in stop_words and len(w) > 2]

    for i in range(len(meaningful)):
        for j in range(i + 1, min(i + 4, len(meaningful) + 1)):
            phrase = ' '.join(meaningful[i:j])
            if phrase not in phrases and len(phrase) > 3:
                phrases.append(phrase)

    for word in meaningful:
        if word not in phrases:
            phrases.append(word)

    return phrases


# ── Context Builder ───────────────────────────────────────────

def build_context(documents: list, response_language: str = 'en') -> str:
    if not documents:
        return "No relevant regulatory documents found in the knowledge base."

    parts = []
    for i, doc in enumerate(documents, 1):
        if response_language == 'bn' and doc.get('title_bn'):
            title    = doc['title_bn']
            en_title = doc.get('title_en', '')
        else:
            title    = doc.get('title_en', '')
            en_title = ''

        ref    = doc.get('circular_ref') or 'N/A'
        body   = doc.get('issuing_body', '')
        dept   = doc.get('department', '')
        dt     = doc.get('issue_date', '')
        url    = doc.get('primary_url', '')
        status = doc.get('status', 'active')
        summary = doc.get('summary_en') or ''
        sim    = doc.get('similarity')

        part  = f"[DOCUMENT {i}]\n"
        part += f"Title: {title}\n"
        if en_title:
            part += f"English Title: {en_title}\n"
        part += f"Circular Reference: {ref}\n"
        part += f"Issuing Authority: {body}"
        if dept:
            part += f" — {dept} Department"
        part += f"\nDate Issued: {dt}\n"
        if status != 'active':
            part += f"⚠️ STATUS: {status.upper()} — This circular may have been superseded\n"
        if sim:
            part += f"Relevance Score: {sim:.2f}\n"
        if summary:
            part += f"Summary: {summary[:600]}\n"
        part += f"Source: {url}"
        parts.append(part)

    separator = "\n\n" + "─" * 50 + "\n\n"
    return separator.join(parts)


# ── LLM Calls ─────────────────────────────────────────────────

@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=6))
async def call_groq(system_prompt: str, user_message: str) -> str:
    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":       settings.LLM_MODEL_ID,
        "messages":    [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        "temperature": 0.1,
        "max_tokens":  1000,
        "stream":      False,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers, json=payload,
        )
        if response.status_code != 200:
            logger.error(f"Groq error {response.status_code}: {response.text[:200]}")
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=5, max=15))
async def call_huggingface(system_prompt: str, user_message: str) -> str:
    full_prompt = f"{system_prompt}\n\n{user_message}"
    api_url     = f"https://api-inference.huggingface.co/models/{settings.LLM_MODEL_ID}"
    headers     = {"Authorization": f"Bearer {settings.HUGGINGFACE_API_TOKEN}"}
    payload     = {
        "inputs":     full_prompt,
        "parameters": {"max_new_tokens": 800, "temperature": 0.1, "return_full_text": False},
        "options":    {"wait_for_model": True},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(api_url, headers=headers, json=payload)
        if response.status_code == 503:
            raise Exception("Model loading, retry")
        response.raise_for_status()
        result = response.json()
    if isinstance(result, list) and result:
        return result[0].get("generated_text", "").strip()
    return ""


async def call_llm(system_prompt: str, user_message: str) -> str:
    if getattr(settings, "GROQ_API_KEY", ""):
        try:
            return await call_groq(system_prompt, user_message)
        except Exception as e:
            logger.warning(f"Groq failed: {e}, trying HuggingFace...")
    if getattr(settings, "HUGGINGFACE_API_TOKEN", ""):
        try:
            return await call_huggingface(system_prompt, user_message)
        except Exception as e:
            logger.warning(f"HuggingFace failed: {e}")
    raise Exception("All LLM providers unavailable")


# ── Main RAG Pipeline ─────────────────────────────────────────

async def process_query(
    query_text: str,
    language:   str = 'auto',
    user_id:    str = None,
) -> dict:
    """
    Full bilingual RAG pipeline:
    1. Detect language
    2. Bilingual semantic search (expand + translate + keyword boost)
    3. Build rich context from top documents
    4. Generate AI answer with citations and disclaimer
    5. Audit log
    """
    start_time = time.time()

    # Step 1: Detect language
    if language == 'auto' or language not in ('en', 'bn'):
        detected = detect_language(query_text)
    else:
        detected = language

    logger.info(f"Query [{detected}]: {query_text[:80]}")

    # Step 2: Choose prompts
    system_prompt = SYSTEM_PROMPT_BN if detected == 'bn' else SYSTEM_PROMPT_EN
    disclaimer    = DISCLAIMER_BN    if detected == 'bn' else DISCLAIMER_EN

    # Step 3: Bilingual semantic search — pass detected language
    logger.info("Running bilingual semantic search...")
    documents = get_relevant_documents_semantic(
        query_text,
        limit=6,
        query_lang=detected,
    )
    logger.info(f"Found {len(documents)} relevant documents")

    # Step 4: Build context
    context = build_context(documents, response_language=detected)

    # Step 5: Build LLM prompt
    if detected == 'bn':
        user_message = (
            f"নিয়ন্ত্রক দলিলসমূহ (বাংলা ও ইংরেজি উভয় উৎস থেকে):\n"
            f"{context}\n\n"
            f"ব্যবহারকারীর প্রশ্ন: {query_text}\n\n"
            f"অনুগ্রহ করে উপরের দলিলের ভিত্তিতে বিস্তারিত উত্তর দিন। "
            f"প্রতিটি পয়েন্টের জন্য সার্কুলার রেফারেন্স নম্বর উল্লেখ করুন। "
            f"সর্বশেষ বৈধ সার্কুলার চিহ্নিত করুন।"
        )
    else:
        user_message = (
            f"REGULATORY DOCUMENTS (searched in both English and Bangla):\n"
            f"{context}\n\n"
            f"USER QUESTION: {query_text}\n\n"
            f"Please provide a detailed, well-structured answer based strictly on "
            f"the documents above.\n"
            f"Requirements:\n"
            f"- Cite specific circular reference numbers for each key point\n"
            f"- If multiple circulars exist on same topic, identify the most recent one\n"
            f"- Note if any cited circular has been superseded\n"
            f"- If information is insufficient, state what is missing and suggest "
            f"contacting the authority directly\n"
            f"- Use numbered points for clarity"
        )

    # Step 6: Generate AI answer
    answer = ""
    try:
        if not getattr(settings, "GROQ_API_KEY", "") and \
           not getattr(settings, "HUGGINGFACE_API_TOKEN", ""):
            answer = "AI provider not configured. Please add GROQ_API_KEY to .env file."
        else:
            answer = await call_llm(system_prompt, user_message)

        has_disclaimer = (
            "REGULATORY DISCLAIMER" in answer or
            "নিয়ন্ত্রক দাবিত্যাগ" in answer or
            "legal advice" in answer.lower()
        )
        if not has_disclaimer:
            answer = answer + "\n\n" + disclaimer

    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        if detected == 'bn':
            answer = (
                f"এআই সেবা সাময়িকভাবে অনুপলব্ধ। "
                f"{len(documents)}টি প্রাসঙ্গিক দলিল পাওয়া গেছে।"
                f"\n\n{disclaimer}"
            )
        else:
            answer = (
                f"AI service temporarily unavailable. "
                f"Found {len(documents)} relevant documents below."
                f"\n\n{disclaimer}"
            )

    latency_ms = int((time.time() - start_time) * 1000)
    logger.info(f"Query completed in {latency_ms}ms")

    # Step 7: Build citations
    citations      = []
    has_superseded = False
    for doc in documents:
        if doc.get("status") == "superseded":
            has_superseded = True
        citations.append({
            "document_id":  doc.get("id") or doc.get("document_id", ""),
            "title_en":     doc.get("title_en", ""),
            "title_bn":     doc.get("title_bn"),
            "circular_ref": doc.get("circular_ref"),
            "issuing_body": doc.get("issuing_body", ""),
            "issue_date":   str(doc.get("issue_date", "")),
            "primary_url":  doc.get("primary_url", ""),
            "status":       doc.get("status", "active"),
            "language":     doc.get("language", "english"),
            "similarity":   doc.get("similarity"),
        })

    # Step 8: Audit log
    try:
        supabase.table("query_audit_log").insert({
            "query_text":     query_text,
            "query_language": detected,
            "response_text":  answer[:2000],
            "citations":      [c["document_id"] for c in citations if c["document_id"]],
            "model_used":     settings.LLM_MODEL_ID,
            "latency_ms":     latency_ms,
        }).execute()
    except Exception as e:
        logger.warning(f"Audit log failed: {e}")

    return {
        "answer":                  answer,
        "citations":               citations,
        "model_used":              settings.LLM_MODEL_ID,
        "latency_ms":              latency_ms,
        "query_language":          detected,
        "disclaimer":              disclaimer,
        "has_superseded_citation": has_superseded,
    }