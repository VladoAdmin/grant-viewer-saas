#!/usr/bin/env python3
"""Test attachment processing on one grant call."""
import os, json, time, hashlib, requests, tiktoken, pdfplumber
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")
from openai import OpenAI

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}
HEADERS_MIN = dict(HEADERS); HEADERS_MIN["Prefer"] = "return=minimal"

openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
enc = tiktoken.encoding_for_model("gpt-4")

TEST_CALL_ID = "3d602a6c-9856-4004-8a37-d1e34345e232"
PDF_DIR = "/tmp/grant_attachments"
os.makedirs(PDF_DIR, exist_ok=True)


def count_tokens(text):
    return len(enc.encode(text))


def chunk_text(text, target=768, max_t=1024):
    paragraphs = text.split("\n")
    chunks, current, cur_t = [], [], 0
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        pt = count_tokens(p)
        if cur_t + pt > target and current:
            chunks.append("\n".join(current))
            current, cur_t = [], 0
        current.append(p)
        cur_t += pt
    if current:
        chunks.append("\n".join(current))
    return chunks


# Step 1: Ensure v2_enriched_calls stub exists
print("=== Step 1: Ensure v2_enriched_calls stub ===")
r = requests.get(
    f"{SUPABASE_URL}/rest/v1/v2_enriched_calls?id=eq.{TEST_CALL_ID}&select=id",
    headers=HEADERS,
)
if not r.json():
    r2 = requests.get(
        f"{SUPABASE_URL}/rest/v1/grant_calls_v2?id=eq.{TEST_CALL_ID}&select=*",
        headers=HEADERS,
    )
    call = r2.json()[0]
    stub = {
        "id": TEST_CALL_ID,
        "title_clean": call["title"],
        "enrichment_status": "attachment_processing",
    }
    r3 = requests.post(
        f"{SUPABASE_URL}/rest/v1/v2_enriched_calls", headers=HEADERS_MIN, json=stub
    )
    print(f"  Inserted stub: {r3.status_code}")
    if r3.status_code >= 400:
        print(f"  Error: {r3.text[:300]}")
else:
    print("  Already exists")

# Step 2: Get PDF attachments
print("\n=== Step 2: Get PDF attachments ===")
r = requests.get(
    f"{SUPABASE_URL}/rest/v1/grant_call_attachments?grant_call_id=eq.{TEST_CALL_ID}&select=*",
    headers=HEADERS,
)
all_atts = r.json()
pdf_atts = [a for a in all_atts if (a.get("file_type") or "").upper() == "PDF"]
print(f"  Total: {len(all_atts)}, PDFs: {len(pdf_atts)}")
for a in pdf_atts:
    print(f"    • {a['name'][:70]}")
    print(f"      {a['url'][:100]}")

# Step 3: Download, extract, chunk, embed (first 2 PDFs)
print("\n=== Step 3: Process PDFs (first 2) ===")
all_chunk_rows = []

for i, att in enumerate(pdf_atts[:2]):
    print(f"\n--- PDF {i+1}/{min(2, len(pdf_atts))}: {att['name'][:60]} ---")
    try:
        # Download
        fname = hashlib.md5(att["url"].encode()).hexdigest() + ".pdf"
        fpath = os.path.join(PDF_DIR, fname)
        if not (os.path.exists(fpath) and os.path.getsize(fpath) > 0):
            r = requests.get(
                att["url"], timeout=60, headers={"User-Agent": "Mozilla/5.0"}
            )
            r.raise_for_status()
            with open(fpath, "wb") as f:
                f.write(r.content)
        fsize = os.path.getsize(fpath)
        print(f"  Downloaded: {fsize:,} bytes")

        # Extract text
        texts = []
        with pdfplumber.open(fpath) as pdf:
            print(f"  Pages: {len(pdf.pages)}")
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    texts.append(t)
        text = "\n\n".join(texts)
        tokens = count_tokens(text)
        print(f"  Extracted: {len(text):,} chars, {tokens:,} tokens")

        if len(text.strip()) < 50:
            print("  SKIP: insufficient text")
            continue

        # Show preview
        print(f"  Preview (500 chars):")
        print(f"  {'─'*60}")
        print(f"  {text[:500]}")
        print(f"  {'─'*60}")

        # Chunk
        chunks = chunk_text(text)
        print(f"  Chunks: {len(chunks)} (avg {tokens // max(len(chunks),1)} tok/chunk)")

        # Embed
        embs = []
        for j in range(0, len(chunks), 100):
            batch = chunks[j : j + 100]
            resp = openai_client.embeddings.create(
                model="text-embedding-3-small", input=batch
            )
            embs.extend([d.embedding for d in resp.data])
            time.sleep(0.3)
        print(f"  Embeddings: {len(embs)} vectors (1536-dim)")

        # Build rows
        for idx, (ch, emb) in enumerate(zip(chunks, embs)):
            all_chunk_rows.append(
                {
                    "call_id": TEST_CALL_ID,
                    "source_type": "pdf",
                    "source_url": att["url"],
                    "chunk_index": idx,
                    "chunk_text": ch,
                    "token_count": count_tokens(ch),
                    "embedding": json.dumps(emb),
                }
            )

    except Exception as e:
        print(f"  ERROR: {e}")

# Step 4: Insert
print(f"\n=== Step 4: Insert {len(all_chunk_rows)} chunks ===")
if all_chunk_rows:
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/v2_call_chunks",
        headers=HEADERS_MIN,
        json=all_chunk_rows,
    )
    print(f"  HTTP {r.status_code}")
    if r.status_code >= 400:
        print(f"  Error: {r.text[:500]}")
    else:
        print("  ✅ Inserted OK")

# Step 5: Verify
print("\n=== Step 5: Verify in DB ===")
r = requests.get(
    f"{SUPABASE_URL}/rest/v1/v2_call_chunks?call_id=eq.{TEST_CALL_ID}"
    f"&select=id,chunk_index,token_count,source_url&order=chunk_index",
    headers=HEADERS,
)
rows = r.json()
print(f"  Rows in v2_call_chunks: {len(rows)}")
if rows:
    total_tok = sum(r_["token_count"] for r_ in rows)
    urls = set(r_["source_url"] for r_ in rows)
    print(f"  Total tokens: {total_tok:,}")
    print(f"  Source URLs: {len(urls)}")
    for u in urls:
        cnt = len([r_ for r_ in rows if r_["source_url"] == u])
        print(f"    • {cnt} chunks from ...{u[-50:]}")

print("\n=== TEST COMPLETE ===")
