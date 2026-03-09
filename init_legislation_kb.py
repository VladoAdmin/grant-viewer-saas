"""Initialize base legislation knowledge base."""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from v2.legislation_ingestion import ingest_legislation_document


# Slovak documents - tested and working
BASE_DOCUMENTS = [
    {
        "title": "Systém implementácie Plánu obnovy a odolnosti SR (SIPOO)",
        "url": "https://www.planobnovy.sk/site/assets/files/1236/sipoo.pdf",
        "doc_type": "methodology",
        "jurisdiction": "SK",
    },
    {
        "title": "Metodický dokument RO pre Program Slovensko č. 12",
        "url": "https://eurofondy.gov.sk/wp-content/uploads/2024/04/MU_c_12_metodika_posudzovania_PvT.pdf",
        "doc_type": "methodology",
        "jurisdiction": "SK",
    },
    {
        "title": "Metodický dokument RO pre Program Slovensko č. 8",
        "url": "https://nitra.sk/wp-content/uploads/2025/07/Metodicky-dokument-riadiaceho-organu-pre-Program-Slovensko-c.-8.pdf",
        "doc_type": "methodology",
        "jurisdiction": "SK",
    },
]

# EU documents - need alternative source (EUR-Lex blocks downloads)
EU_DOCUMENTS = [
    {
        "title": "Regulation (EU) 2021/1060 (CPR) - Common Provisions",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32021R1060",
        "doc_type": "regulation",
        "jurisdiction": "EU",
        "note": "EUR-Lex blocks direct download - needs manual import or alternative source",
    },
]


def main():
    results = []
    
    print("="*60)
    print("GRANTBOT LEGISLATION KNOWLEDGE BASE INITIALIZATION")
    print("="*60)
    
    # Process Slovak documents
    print("\n📄 Processing Slovak legislation documents...\n")
    for doc in BASE_DOCUMENTS:
        print(f"Ingesting: {doc['title']}")
        try:
            res = ingest_legislation_document(
                title=doc['title'],
                source_url=doc['url'],
                doc_type=doc['doc_type'],
                jurisdiction=doc['jurisdiction'],
            )
            results.append({**doc, **res, "status": "success"})
            print(f"  ✓ Success: {res.get('chunk_count', 0)} chunks created")
        except Exception as e:
            print(f"  ✗ Error: {e}")
            results.append({**doc, "status": "error", "error": str(e)})
    
    # Note about EU documents
    print("\n⚠️  EU Documents (skipped - need manual import):")
    for doc in EU_DOCUMENTS:
        print(f"  - {doc['title']}")
        print(f"    Note: {doc['note']}")
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY:")
    successful = [r for r in results if r.get('status') == 'success']
    failed = [r for r in results if r.get('status') == 'error']
    print(f"  ✓ Successful: {len(successful)}")
    print(f"  ✗ Failed: {len(failed)}")
    
    total_chunks = sum(r.get('chunk_count', 0) for r in successful)
    print(f"  📊 Total chunks created: {total_chunks}")
    
    if failed:
        print("\nFailed documents:")
        for f in failed:
            print(f"  - {f['title']}: {f.get('error', 'unknown')}")
    
    print("\n✅ Initialization complete!")
    print("="*60)


if __name__ == "__main__":
    main()
