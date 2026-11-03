"""Affiliation string matching (OpenAlex institution name vs ACL-declared affiliation) and smear detection."""
from __future__ import annotations

import re
from typing import Any

from src.data.normalize import fold

STOP = {"university", "of", "the", "and", "institute", "for", "de", "technology", "department", "school", "college",
        "science", "sciences", "national", "research", "center", "centre", "lab", "laboratory", "labs", "inc", "ltd",
        "group", "computer", "engineering", "faculty", "language", "ai", "artificial", "intelligence", "key", "state",
        "united", "states", "kingdom", "china", "india", "germany", "france", "japan", "korea", "south", "canada", "usa",
        "uk", "us", "academy", "corporation", "company", "co", "llc", "gmbh", "at", "in", "la", "le", "der", "und", "di"}
ALIASES = {"mit": "massachusetts institute technology", "cmu": "carnegie mellon", "ucla": "california los angeles",
           "ucsd": "california san diego", "uiuc": "illinois urbana", "kaist": "korea advanced", "epfl": "lausanne",
           "nus": "national singapore", "ntu": "nanyang", "hkust": "hong kong", "ustc": "china",
           "usc": "southern california", "umass": "massachusetts", "unc": "north carolina", "jhu": "johns hopkins",
           "upenn": "pennsylvania", "uw": "washington", "cuhk": "chinese hong kong", "sjtu": "shanghai jiao tong",
           "ucas": "chinese", "cas": "chinese", "msr": "microsoft", "umd": "maryland", "lmu": "ludwig maximilians munchen",
           "skoltech": "skolkovo", "tum": "technical munich", "kit": "karlsruhe", "ust": "hong kong",
           "deepmind": "google deepmind", "fair": "meta", "facebook": "meta", "a star": "agency science technology research"}


def _strip(s: str) -> str:
    return re.sub(r"\([^)]*\)", " ", s or "")


# language-neutral normalisation of common institution words (generic, not tuned to any sample)
_TRANSLATE = {"universitat": "university", "universitaet": "university", "universite": "university",
              "universidad": "university", "universita": "university", "universiteit": "university",
              "universidade": "university", "technische": "technical", "technischen": "technical",
              "munchen": "munich", "zurich": "zurich", "wien": "vienna", "koln": "cologne", "praha": "prague",
              "jingdong": "jd", "jpmorgan": "jp morgan"}


def _norm_inst(s: str) -> str:
    s = fold(s)
    return " ".join(_TRANSLATE.get(w, w) for w in s.split())


def _toks(s: str) -> set[str]:
    return {w for w in _norm_inst(s).split() if w not in STOP and len(w) > 1}


def affiliation_agrees(oa_name: str, declared: str) -> bool:
    a = _norm_inst(declared)
    for short, long_ in ALIASES.items():
        if re.search(rf"\b{short}\b", a):
            a += " " + long_
    o = _norm_inst(_strip(oa_name))
    if o and (o in a or (len(a) > 3 and a in o)):
        return True
    oa_alias = o
    for short, long_ in ALIASES.items():
        if re.search(rf"\b{short}\b", o):
            oa_alias += " " + long_
    ot, at = _toks(oa_alias), _toks(a)
    if not ot or not at:
        return False
    inter = ot & at
    return len(inter) / len(ot) >= 0.5 or len(inter) / len(at) >= 0.5


def is_smeared(work: dict[str, Any]) -> bool:
    """OpenAlex sometimes copies all paper-level affiliations onto every author. Detect that pattern."""
    au = work.get("authorships") or []
    if len(au) < 2:
        return False
    sets = [frozenset(a.get("raw_affiliation_strings") or []) for a in au]
    if len(set(sets)) == 1 and len(sets[0]) >= 2:
        return True
    isets = [frozenset(i.get("id") for i in a.get("institutions") or []) for a in au]
    return len(set(isets)) == 1 and len(isets[0]) >= 3
