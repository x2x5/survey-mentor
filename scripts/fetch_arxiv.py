#!/usr/bin/env python3
"""
fetch_arxiv.py — Search arXiv for a paper, download its PDF and LaTeX source.

Part of the survey-as-mentor skill.

Usage:
    python3 fetch_arxiv.py "<paper-title-or-arxiv-id>" --output-dir <base_dir>

The script:
  1. Queries the arXiv API to find the paper (or recognizes an arXiv ID)
  2. Downloads the PDF to <base_dir>/<paper_name>/paper.pdf
  3. Downloads and extracts the LaTeX source to <base_dir>/<paper_name>/latex/

PDF is downloaded first, so even if LaTeX source is unavailable (PDF-only paper),
the PDF is still saved and metadata is recorded.
"""

import argparse
import json
import os
import re
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Set

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_EPRINT_URL = "https://arxiv.org/e-print"


# ---------------------------------------------------------------------------
#  arXiv API helpers
# ---------------------------------------------------------------------------


def search_arxiv(query: str, max_results: int = 5) -> List[Dict]:
    """Search arXiv by title. Returns a list of result dicts."""
    params = {
        "search_query": f'ti:"{query}"',
        "max_results": str(max_results),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(url, headers={"User-Agent": "SurveyMentor/1.0"})
    resp = urllib.request.urlopen(req, timeout=30)
    xml_data = resp.read().decode("utf-8")

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    root = ET.fromstring(xml_data)
    entries = root.findall("atom:entry", ns)

    results = []
    for entry in entries:
        title_el = entry.find("atom:title", ns)
        title = (
            title_el.text.strip().replace("\n", " ")
            if title_el is not None
            else "Unknown"
        )

        id_el = entry.find("atom:id", ns)
        arxiv_id = ""
        if id_el is not None:
            m = re.search(r"/(\d+\.\d+)(v\d+)?", id_el.text)
            if m:
                arxiv_id = m.group(1) + (m.group(2) or "")

        summary_el = entry.find("atom:summary", ns)
        summary = (
            summary_el.text.strip().replace("\n", " ") if summary_el is not None else ""
        )

        authors = []
        for author in entry.findall("atom:author", ns):
            name_el = author.find("atom:name", ns)
            if name_el is not None:
                authors.append(name_el.text)

        results.append(
            {
                "id": arxiv_id,
                "title": title,
                "summary": summary[:500],
                "authors": authors,
            }
        )

    return results


# ---------------------------------------------------------------------------
#  Download / extraction
# ---------------------------------------------------------------------------


def _looks_like_pdf(data: bytes) -> bool:
    """Check whether *data* starts with the PDF magic bytes."""
    return data[:4] == b"%PDF"


# ---------------------------------------------------------------------------
#  PDF download
# ---------------------------------------------------------------------------


def download_pdf(arxiv_id: str, output_dir: str) -> Optional[str]:
    """Download the PDF from arXiv and save it as paper.pdf.

    Returns the path to the saved PDF, or None if all attempts failed.
    """
    os.makedirs(output_dir, exist_ok=True)
    pdf_path = os.path.join(output_dir, "paper.pdf")

    # Build candidate URLs: try versioned first (if present), then base ID
    urls_to_try = []
    if re.search(r"v\d+$", arxiv_id):
        urls_to_try.append(f"https://arxiv.org/pdf/{arxiv_id}.pdf")
        urls_to_try.append(f"https://arxiv.org/pdf/{arxiv_id}")
    base_id = re.sub(r"v\d+$", "", arxiv_id)
    urls_to_try.append(f"https://arxiv.org/pdf/{base_id}.pdf")
    urls_to_try.append(f"https://arxiv.org/pdf/{base_id}")

    # Deduplicate while preserving order
    seen_urls: Set[str] = set()
    unique_urls: List[str] = []
    for u in urls_to_try:
        if u not in seen_urls:
            seen_urls.add(u)
            unique_urls.append(u)

    for url in unique_urls:
        try:
            print(f"  Downloading PDF from {url} …")
            req = urllib.request.Request(
                url, headers={"User-Agent": "PaperCodeAudit/1.0"}
            )
            resp = urllib.request.urlopen(req, timeout=60)
            data = resp.read()

            if data[:4] == b"%PDF":
                with open(pdf_path, "wb") as f:
                    f.write(data)
                print(f"  \u2713 PDF saved \u2192 {pdf_path}")
                return pdf_path
            else:
                print(f"  Warning: response from {url} is not a PDF")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            print(f"  Warning: HTTP {e.code} downloading PDF from {url}")
        except Exception as e:
            print(f"  Warning: {e}")

    print(f"  \u2717 Could not download PDF for {arxiv_id}")
    return None


def download_source(arxiv_id: str, output_dir: str) -> None:
    """Download the LaTeX source from arXiv and extract it.

    Raises RuntimeError if the download is a PDF (i.e. the author did not
    upload LaTeX source).  Caller should catch this and report gracefully.
    """
    os.makedirs(output_dir, exist_ok=True)

    base_id = re.sub(r"v\d+$", "", arxiv_id)  # strip version for download URL
    url = f"{ARXIV_EPRINT_URL}/{base_id}"

    print(f"  Downloading source from {url} …")
    req = urllib.request.Request(url, headers={"User-Agent": "SurveyMentor/1.0"})
    resp = urllib.request.urlopen(req, timeout=60)
    raw_data = resp.read()

    # --- Detect PDF early ---------------------------------------------------
    if _looks_like_pdf(raw_data):
        # Clean up the empty directory we just created
        os.rmdir(output_dir)
        raise RuntimeError(
            f"arXiv paper {arxiv_id} has no LaTeX source — only a PDF is available. "
            "Cannot extract claims without LaTeX source."
        )

    # --- Try to extract as tarball -------------------------------------------
    with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp:
        tmp.write(raw_data)
        tmp_path = tmp.name

    extracted = False
    try:
        # arXiv typically returns .tar.gz
        try:
            with tarfile.open(tmp_path, "r:gz") as tar:
                tar.extractall(path=output_dir)
            print(f"  Extracted gzipped tarball → {output_dir}")
            extracted = True
        except tarfile.ReadError:
            # Fall back to uncompressed tar
            try:
                with tarfile.open(tmp_path, "r:") as tar:
                    tar.extractall(path=output_dir)
                print(f"  Extracted uncompressed tarball → {output_dir}")
                extracted = True
            except tarfile.ReadError:
                # Last resort: single .tex file uploaded directly
                # (arXiv occasionally returns a lone .tex instead of a tarball)
                print(f"  Not a tarball — checking if it is a valid .tex file …")
                # Read first few hundred bytes as text to guess if it's TeX
                text_start = raw_data[:1024].decode("utf-8", errors="replace")
                if re.search(
                    r"\\(documentclass|section|begin\{document\})", text_start
                ):
                    tex_path = os.path.join(output_dir, f"{base_id}.tex")
                    with open(tex_path, "wb") as f:
                        f.write(raw_data)
                    print(f"  Saved single .tex file → {tex_path}")
                    extracted = True
                else:
                    # Don't know what this is — clean up and bail
                    os.rmdir(output_dir)
                    raise RuntimeError(
                        f"Download from arXiv for {arxiv_id} is not a LaTeX tarball "
                        "or .tex file, and not a PDF. Cannot process."
                    )
    finally:
        os.unlink(tmp_path)

    # --- Report TeX files found ---------------------------------------------
    tex_count = 0
    for root, _dirs, files in os.walk(output_dir):
        for f in files:
            if f.endswith(".tex"):
                tex_count += 1
                print(f"    TeX: {os.path.relpath(os.path.join(root, f), output_dir)}")
    print(f"  ({tex_count} TeX file(s) total)")


# ---------------------------------------------------------------------------
#  Misc
# ---------------------------------------------------------------------------


def sanitize_paper_name(title: str) -> str:
    """Turn a paper title into a safe, short directory name."""
    name = title.lower().strip()
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"[\s-]+", "-", name)
    name = name[:80].strip("-")
    return name


# ---------------------------------------------------------------------------
#  CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search arXiv and download PDF + LaTeX source"
    )
    parser.add_argument("query", help="Paper title or arXiv ID (e.g. 1706.03762)")
    parser.add_argument(
        "--output-dir", "-o", default=".", help="Base output directory (default: cwd)"
    )
    parser.add_argument(
        "--max-results",
        "-m",
        type=int,
        default=5,
        help="Max search results (default: 5)",
    )
    args = parser.parse_args()

    query = args.query.strip()

    # --- Step 1: locate the paper -------------------------------------------
    arxiv_id_match = re.match(r"^(\d+\.\d+)(v\d+)?$", query)
    if arxiv_id_match:
        print(f"Input recognised as arXiv ID: {query}")
        results = [
            {"id": query, "title": f"Paper {query}", "authors": [], "summary": ""}
        ]
    else:
        print(f'Searching arXiv for: "{query}"')
        results = search_arxiv(query, args.max_results)

    if not results:
        print("No papers found.")
        sys.exit(1)

    if len(results) > 1:
        print(f"\nFound {len(results)} papers:")
        for i, r in enumerate(results):
            authors = ", ".join(r["authors"][:3])
            print(f"  [{i + 1}] {r['title']}")
            print(f"       ID: {r['id']}  |  {authors}")
        print()
        try:
            choice = int(input(f"Select paper (1–{len(results)}): ")) - 1
            if choice < 0 or choice >= len(results):
                print("Invalid choice.")
                sys.exit(1)
        except (ValueError, EOFError):
            print("Invalid input.")
            sys.exit(1)
    else:
        choice = 0

    paper = results[choice]
    paper_name = sanitize_paper_name(paper["title"])
    # Prepend creation timestamp for chronological sorting: MMDD-HHMMSS-papername
    from datetime import datetime
    ts = datetime.now().strftime("%m%d-%H%M%S")
    paper_name = f"{ts}-{paper_name}"
    latex_dir = os.path.join(args.output_dir, paper_name, "latex")
    meta_dir = os.path.dirname(latex_dir)  # <paper_name>/
    os.makedirs(meta_dir, exist_ok=True)

    print(f"\nPaper: {paper['title']}")
    print(f"  arXiv ID : {paper['id']}")
    print(f"  Directory: {meta_dir}")

    # --- Step 2: save metadata (before any downloads) -----------------------
    with open(os.path.join(meta_dir, "paper.json"), "w", encoding="utf-8") as f:
        json.dump(paper, f, indent=2, ensure_ascii=False)
    print(f"  Metadata   → {os.path.join(meta_dir, 'paper.json')}")

    # --- Step 3: download PDF (always available for arXiv papers) -----------
    pdf_path = download_pdf(paper["id"], meta_dir)

    # --- Step 4: download & extract LaTeX source ----------------------------
    try:
        download_source(paper["id"], latex_dir)
    except RuntimeError as e:
        print(f"\n  ✗ {e}")
        if pdf_path:
            print(f"  (PDF was saved to {pdf_path} but LaTeX source is unavailable.)")
        else:
            print("  (Neither PDF nor LaTeX source are available.)")
        sys.exit(1)

    print(f"\nDone. LaTeX source → {latex_dir}")
    if pdf_path:
        print(f"      PDF         → {pdf_path}")


if __name__ == "__main__":
    main()
