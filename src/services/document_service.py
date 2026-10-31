"""Document lifecycle operations used by the UI."""
from __future__ import annotations

import re
import shutil

from src import config, db


def delete_document(doc_id: str) -> bool:
    """Delete a parsed document and all of its stored context."""
    if not re.fullmatch(r"[0-9a-f]{12}", doc_id):
        raise ValueError("Invalid document ID")

    conn = db.connect()
    try:
        db.init_db(conn)
        if not db.get_document(conn, doc_id):
            return False

        upload_path = config.doc_upload_path(doc_id)
        if upload_path.exists():
            upload_path.unlink()
        for path in (config.doc_pages_dir(doc_id), config.doc_index_dir(doc_id)):
            if path.exists():
                shutil.rmtree(path)
        return db.delete_document(conn, doc_id)
    finally:
        conn.close()
