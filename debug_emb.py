# Save as debug_emb.py
import sys
sys.path.insert(0, '.')
import numpy as np
import json
from sentence_transformers import SentenceTransformer
from app.database import supabase

model     = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
query_emb = model.encode("Excise Duty on Bank Accounts", normalize_embeddings=True)

# Get the specific doc
r = (
    supabase.table("documents")
    .select("id, title_en, topic_tags")
    .ilike("title_en", "%Modified rate of excise%")
    .limit(1)
    .execute()
)

if r.data:
    doc    = r.data[0]
    doc_id = doc['id']
    print(f"Title: {doc['title_en']}")
    print(f"Tags : {doc['topic_tags']}")

    chunk = (
        supabase.table("document_chunks")
        .select("chunk_text, embedding")
        .eq("document_id", doc_id)
        .limit(1)
        .execute()
    )

    if chunk.data:
        chunk_text = chunk.data[0]['chunk_text']
        stored_emb = np.array(json.loads(chunk.data[0]['embedding']))
        sim        = np.dot(stored_emb, query_emb)

        print(f"\nSimilarity: {sim:.4f}")
        print(f"\nFULL chunk_text:\n{chunk_text}")

        # Now test what score we'd get with the RIGHT text
        correct_text = (
            "Modified rate of excise duty for Bank services. | "
            "Modified rate of excise duty for Bank services. | "
            "excise duty bank accounts tax levy charge surcharge government revenue | "
            "Circular reference: BRPD Circular Letter No. 07 | "
            "Issued by BB BRPD department | "
            "Category: Credit Policy & Lending | "
            "Topics: general, excise duty | "
            "excise duty bank accounts tax levy charge surcharge government revenue"
        )
        correct_emb = model.encode(correct_text, normalize_embeddings=True)
        correct_sim = np.dot(correct_emb, query_emb)
        print(f"\nWith correct text, similarity would be: {correct_sim:.4f}")