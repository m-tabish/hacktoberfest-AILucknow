"""Hybrid retrieval: custom pure-Python BM25 + optional FAISS.

Returns candidate PAGES (not just chunks) — the LLM reads whole pages, and
page-level aggregation is what makes dense table pages (e.g. p101) rank well:
the entity's table_row chunk, narrative chunks and the page chunk all vote
for the same page.

No rank-bm25 dependency: BM25Okapi is implemented here (~40 lines).
"""
from __future__ import annotations

import math
import pickle
from collections import Counter, defaultdict

from src import config, db
from src.ingest.normalize import normalize_label, tokenize
from src.qa.entity import METRIC_SYNONYMS

_corpus_cache: dict = {}


class BM25Okapi:
    def __init__(self, corpus_tokens: list):
        self.corpus = corpus_tokens
        self.n = len(corpus_tokens)
        self.avgdl = (sum(len(t) for t in corpus_tokens) / self.n) if self.n else 0.0
        df: Counter = Counter()
        for toks in corpus_tokens:
            df.update(set(toks))
        self.idf = {
            t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()
        }
        self.tfs = [Counter(t) for t in corpus_tokens]

    def score(self, query_tokens: list, idx: int) -> float:
        if self.n == 0:
            return 0.0
        k1, b = 1.5, 0.75
        tf = self.tfs[idx]
        dl = len(self.corpus[idx]) or 1
        s = 0.0
        for t in set(query_tokens):
            if t not in tf:
                continue
            idf = self.idf.get(t, 0.0)
            f = tf[t]
            s += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / (self.avgdl or 1)))
        return s


def _load_corpus(conn, doc_id: str) -> list:
    if doc_id in _corpus_cache:
        return _corpus_cache[doc_id]
    corpus = None
    pkl = config.doc_index_dir(doc_id) / "bm25.pkl"
    if pkl.exists():
        try:
            with open(pkl, "rb") as f:
                corpus = pickle.load(f)["corpus"]
        except Exception:
            corpus = None
    if corpus is None:  # build on the fly from SQLite
        rows = db.get_chunks(conn, doc_id, ("page", "narrative", "table_row"))
        corpus = [
            {"chunk_id": r["chunk_id"], "page_no": r["page_no"],
             "chunk_type": r["chunk_type"], "tokens": tokenize(r["text"])}
            for r in rows
        ]
    _corpus_cache[doc_id] = corpus
    return corpus


QUERY_STOPWORDS = {
    "what", "was", "were", "is", "are", "the", "of", "in", "on", "how",
    "many", "during", "per", "for", "and", "or", "to", "a", "an", "by",
    "at", "from", "with", "as", "did", "do", "does", "there", "their",
}


def expanded_query_tokens(question: str, ctx) -> list:
    tokens = [t for t in tokenize(question) if t not in QUERY_STOPWORDS]
    if ctx is not None and ctx.metric:
        tokens += METRIC_SYNONYMS.get(ctx.metric, [])
    if ctx is not None and getattr(ctx, "subject", None):
        tokens += ctx.subject.replace("_", " ").split()
    if ctx is not None and ctx.entity_norm:
        tokens += ctx.entity_norm.split()
    return tokens


def _faiss_scores(conn, doc_id: str, question: str) -> dict:
    """Optional: {chunk_id: cosine} from FAISS. {} on any failure."""
    if not config.ENABLE_EMBEDDINGS:
        return {}
    try:
        import faiss
        from sentence_transformers import SentenceTransformer

        idx_path = config.doc_index_dir(doc_id) / "chunks.faiss"
        meta_path = config.doc_index_dir(doc_id) / "faiss_meta.pkl"
        if not idx_path.exists() or not meta_path.exists():
            return {}
        index = faiss.read_index(str(idx_path))
        with open(meta_path, "rb") as f:
            chunk_ids = pickle.load(f)
        model = SentenceTransformer(config.EMBEDDING_MODEL)
        q = model.encode([question], normalize_embeddings=True, show_progress_bar=False)
        sims, idxs = index.search(q, min(10, len(chunk_ids)))
        return {chunk_ids[i]: float(s) for s, i in zip(sims[0], idxs[0]) if i >= 0}
    except Exception:
        return {}


def search_pages(conn, doc_id: str, question: str, ctx=None,
                 top_pages: int | None = None) -> list:
    """Return [{page_no, score, chunks:[chunk dicts]}] sorted by score desc."""
    top_pages = top_pages or config.RETRIEVAL_TOP_PAGES
    corpus = _load_corpus(conn, doc_id)
    if not corpus:
        return []
    bm25 = BM25Okapi([c["tokens"] for c in corpus])
    qtokens = expanded_query_tokens(question, ctx)
    chunk_text_by_id = {}
    rows = db.get_chunks(conn, doc_id, ("page", "narrative", "table_row"))
    for r in rows:
        chunk_text_by_id[r["chunk_id"]] = r["text"]

    entity_norm = ctx.entity_norm if ctx else None
    metric_words = []
    if ctx is not None and ctx.metric:
        metric_words = METRIC_SYNONYMS.get(ctx.metric, [])

    faiss_scores = _faiss_scores(conn, doc_id, question)

    adjusted: list[tuple[float, dict]] = []
    page_entity: dict[int, bool] = {}
    page_entity_in_row: dict[int, bool] = {}
    for i, c in enumerate(corpus):
        s = bm25.score(qtokens, i)
        text_norm = normalize_label(chunk_text_by_id.get(c["chunk_id"], ""))
        bonus = 0.0
        if entity_norm and entity_norm in text_norm:
            bonus += 6.0
            page_entity[c["page_no"]] = True
            if c["chunk_type"] == "table_row":
                bonus += 4.0
                page_entity_in_row[c["page_no"]] = True
        if metric_words and any(w in text_norm for w in metric_words):
            bonus += 1.0
        if c["chunk_id"] in faiss_scores:
            s += 2.0 * max(faiss_scores[c["chunk_id"]], 0.0)
        adjusted.append((s + bonus, c))

    page_scores: dict[int, list] = defaultdict(list)
    for s, c in adjusted:
        if s > 0:
            page_scores[c["page_no"]].append((s, c))
    ranked = []
    for page_no, items in page_scores.items():
        items.sort(key=lambda x: -x[0])
        top = items[:3]
        # best chunk dominates; supporting chunks count at 40% so a page with
        # one decisive table row beats a page with many mediocre mentions
        agg = top[0][0] + 0.4 * sum(s for s, _ in top[1:])
        # questions here are entity-centric: a page that actually contains the
        # entity (ideally as a table row) outranks generic topical pages
        if page_entity.get(page_no):
            agg += 20.0
        if page_entity_in_row.get(page_no):
            agg += 10.0
        # A question with no specific subject (no two-wheeler / weather /
        # road-feature qualifier) asks for the headline figure, which lives in
        # the main summary tables — not in "classified according to ..."
        # breakdown annexures. Downweight those pages for subject-less queries.
        if ctx is not None and not getattr(ctx, "subject", None):
            page_text_norm = " ".join(
                normalize_label(chunk_text_by_id.get(c["chunk_id"], ""))
                for _s, c in items[:6]
            )
            if "classified according" in page_text_norm:
                agg *= 0.85
        ranked.append({
            "page_no": page_no,
            "score": agg,
            "chunks": [
                {"chunk_id": c["chunk_id"], "chunk_type": c["chunk_type"],
                 "page_no": page_no, "text": chunk_text_by_id.get(c["chunk_id"], "")}
                for _s, c in top
            ],
        })
    ranked.sort(key=lambda r: -r["score"])
    return ranked[:top_pages]


def entity_present(conn, doc_id: str, entity_norm: str) -> bool:
    """True if the entity appears anywhere in the document's page text."""
    if not entity_norm:
        return False
    toks = [t for t in entity_norm.split() if len(t) >= 5]
    for _page_no, text in db.all_pages_text(conn, doc_id):
        norm_text = normalize_label(text)
        if entity_norm in norm_text:
            return True
        if toks and all(t in norm_text for t in toks):
            return True
    return False
