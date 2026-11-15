"""End-to-end, part 2 (run in coauthored-browse's environment): serve the announced paper
from the same database and store, check the abstract page, the PDF and the month listing,
and save the rendered pages.

usage: python e2e_check_browse.py DB_PATH STORE_DIR PAPER_ID LISTING_PATH PDF_PATH OUT_DIR
"""
import sys
from pathlib import Path


def main(db_path, store_dir, paper_id, listing, pdf_path, out_dir):
    import os
    os.environ["CLASSIC_DB_URI"] = f"sqlite:///{Path(db_path).resolve()}"  # before arxiv.db binds
    os.environ["LATEXML_DB_URI"] = "sqlite:///:memory:"
    import browse.services.documents as documents
    import browse.services.listing as listing_svc
    from arxiv.db import models
    from sqlalchemy import create_engine
    from browse.factory import create_web_app

    uri = f"sqlite:///{Path(db_path).resolve()}"
    store = f"{Path(store_dir).resolve()}/"
    app = create_web_app(CLASSIC_DB_URI=uri, LATEXML_DB_URI="sqlite:///:memory:",
                         DOCUMENT_ABSTRACT_SERVICE=documents.db_docs,
                         DOCUMENT_LISTING_SERVICE=listing_svc.db_listing,
                         DISSEMINATION_STORAGE_PREFIX=store, SOURCE_STORAGE_PREFIX=store,
                         ABS_PATH_ROOT=store, LATEXML_ENABLED=0, APPLICATION_ROOT="")
    models.configure_db_engine(create_engine(uri), create_engine("sqlite:///:memory:"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        client = app.test_client()
        abs_page = client.get(f"/abs/{paper_id}")
        assert abs_page.status_code == 200, abs_page.status_code
        html = abs_page.get_data(as_text=True)
        (out / "abs.html").write_text(html)
        for needle in (f"coauthored:{paper_id}", "ca-ai-badge", "Authors and contributions",
                       "responsible author"):
            assert needle in html, needle
        assert "arXiv:" not in html
        pdf = client.get(f"/pdf/{paper_id}")
        assert pdf.status_code == 200 and pdf.data == Path(pdf_path).read_bytes(), pdf.status_code
        lst = client.get(listing)
        assert lst.status_code == 200 and f"coauthored:{paper_id}" in lst.get_data(as_text=True)
        (out / "listing.html").write_text(lst.get_data(as_text=True))
        bib = client.get(f"/bibtex/{paper_id}")
        assert bib.status_code == 200
        (out / "citation.bib").write_text(bib.get_data(as_text=True))
        print(bib.get_data(as_text=True))
    print(f"OK: /abs/{paper_id}, /pdf/{paper_id}, {listing} and /bibtex/{paper_id} served; pages in {out}")


if __name__ == "__main__":
    main(*sys.argv[1:7])
