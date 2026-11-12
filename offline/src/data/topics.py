"""Rule-based topic labelling from title + abstract (no ML, no LLM)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

TOPIC_IDS = ("llm", "mt", "qa", "retrieval", "summarization", "safety_eval")


def normalize(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass
class Rule:
    topic: str
    rule_id: str
    pattern: re.Pattern[str]


@dataclass
class TopicResult:
    topics: list[dict[str, Any]]      # rows for paper_topics.jsonl (without paper_id)
    scores: dict[str, int]
    status: str                       # assigned | UNKNOWN | tie_review


class TopicClassifier:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.rule_version = cfg["rule_version"]
        self.threshold = int(cfg["threshold"])
        self.max_topics = int(cfg["max_topics"])
        self.tp, self.ap = int(cfg["title_points"]), int(cfg["abstract_points"])
        self.rules: list[Rule] = []
        for tid, spec in cfg["topics"].items():
            if tid not in TOPIC_IDS:
                raise ValueError(f"unknown topic id {tid}")
            for p in spec["patterns"]:
                self.rules.append(Rule(tid, p["id"], re.compile(p["regex"])))

    @classmethod
    def from_file(cls, path: Path) -> "TopicClassifier":
        with open(path, encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh))

    @staticmethod
    def _span(original: str, norm_match: str) -> str:
        """Return the evidence substring as it appears in the original (NFKC) text."""
        orig = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", original))
        idx = orig.lower().find(norm_match)
        return orig[idx: idx + len(norm_match)] if idx >= 0 else norm_match

    def classify(self, title: str | None, abstract: str | None) -> TopicResult:
        t_norm, a_norm = normalize(title), normalize(abstract)
        scores: dict[str, int] = {}
        evidence: dict[str, tuple[str, str, str]] = {}   # topic -> (rule_id, span, field)
        for rule in self.rules:
            for field, text, orig, pts in (("title", t_norm, title or "", self.tp),
                                           ("abstract", a_norm, abstract or "", self.ap)):
                m = rule.pattern.search(text)
                if not m:
                    continue
                # one credit per (topic, field): several patterns hitting the title count once
                key = f"{rule.topic}:{field}"
                if key in evidence:
                    continue
                evidence[key] = (rule.rule_id, self._span(orig, m.group(0)), field)
                scores[rule.topic] = scores.get(rule.topic, 0) + pts
        eligible = sorted(((s, t) for t, s in scores.items() if s >= self.threshold), key=lambda x: (-x[0], x[1]))
        if not eligible:
            return TopicResult([], scores, "UNKNOWN")
        chosen = eligible[: self.max_topics]
        status = "assigned"
        if len(eligible) > self.max_topics and eligible[self.max_topics][0] == chosen[-1][0]:
            # tie for the last slot: do not choose arbitrarily
            cut = chosen[-1][0]
            chosen = [c for c in chosen if c[0] > cut]
            status = "tie_review"
            if not chosen:
                return TopicResult([], scores, "tie_review")
        rows = []
        for score, topic in chosen:
            ev = evidence.get(f"{topic}:title") or evidence.get(f"{topic}:abstract")
            assert ev is not None
            rows.append({"topic_id": topic, "rule_id": f"{self.rule_version}:{ev[0]}:{ev[2]}",
                         "evidence_span": ev[1], "confidence_band": "rule_high", "score": score})
        return TopicResult(rows, scores, status)
