"""Typed financial document link discovery helpers."""
from __future__ import annotations
from . import (
    canonical_url,
    classify_link,
    discover_document_candidates,
    discover_document_url,
    extract_links,
)

def discover_links(html, base_url, official_domain=True):
    return extract_links(html, base_url, 0, base_url)

def reject_listing_page(candidate):
    cls = candidate.get("link_type") if isinstance(candidate, dict) else None
    return cls != "navigation_page"

def rank_financial_documents(candidates):
    return sorted(candidates, key=lambda c: c.get("candidate_score", 0) if isinstance(c, dict) else 0, reverse=True)
