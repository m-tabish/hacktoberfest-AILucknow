"""Index building for one document.

BM25 (custom, pure Python — see src/qa/hybrid_search.py for the scorer) is
ALWAYS built: we pickle the tokenised corpus. Embeddings + FAISS are optional
enhancements: if sentence-transformers / faiss are missing or disabled, this
silently skips and the system runs BM25-only.
"""
from __future__ import annotations

import pickle

from src import config, db
from src.ingest.normalize import tokenize

BM25_CHUNK_TYPES = ("page", "narrative", "table_row")
EMBED_CHUNK_TYPES = ("narrative", "table_row")


def build_bm25_index(doc_id: str, chunk_rows: list) -> str:
    out_dir = config.doc_index_dir(doc_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    corpus = [
        {
            "chunk_id": r["chunk_id"],
            "page_no": r["page_no"],
            "chunk_type": r["chunk_type"],
            "tokens": tokenize(r["text"]),
        }
        for r in chunk_rows
    ]
    path = out_dir / "bm25.pkl"
    with open(path, "wb") as f:
        pickle.dump({"doc_id": doc_id, "corpus": corpus}, f)
    return str(path)


def try_build_faiss(doc_id: str, conn, chunk_rows: list) -> bool:
    """Optional embeddings. Returns True on success, False (silently) otherwise."""
    if not config.ENABLE_EMBEDDINGS:
        return False
    try:
        # torch (via sentence_transformers) must load before faiss: each ships its own
        # libomp, and faiss-first segfaults on macOS during encode().
        from sentence_transformers import SentenceTransformer
        import faiss
    except Exception:
        return False
    try:
        embed_rows = [r for r in chunk_rows if r["chunk_type"] in EMBED_CHUNK_TYPES]
        if not embed_rows:
            return False
        model = SentenceTransformer(config.EMBEDDING_MODEL, device=config.EMBEDDING_DEVICE,
                                    local_files_only=True)
        vecs = model.encode([r["text"] for r in embed_rows],
                            normalize_embeddings=True, show_progress_bar=False)
        import numpy as np

        arr = np.asarray(vecs, dtype="float32")
        index = faiss.IndexFlatIP(arr.shape[1])
        index.add(arr)
        out_dir = config.doc_index_dir(doc_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(out_dir / "chunks.faiss"))
        with open(out_dir / "faiss_meta.pkl", "wb") as f:
            pickle.dump([r["chunk_id"] for r in embed_rows], f)
        for pos, r in enumerate(embed_rows):
            db.update_chunk_faiss_pos(conn, r["chunk_id"], pos)
        conn.commit()
        return True
    except Exception:
        return False


def index_document(doc_id: str, conn) -> dict:
    """Build all indexes for an already-ingested document."""
    chunk_rows = db.get_chunks(conn, doc_id, BM25_CHUNK_TYPES)
    bm25_path = build_bm25_index(doc_id, chunk_rows)
    faiss_ok = try_build_faiss(doc_id, conn, chunk_rows)
    return {"bm25": bm25_path, "faiss": faiss_ok, "chunks_indexed": len(chunk_rows)}
