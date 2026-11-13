from graphrag.evidence import EvidenceNormalizer, build_citations


def test_invalid_source_does_not_become_fact_or_citation() -> None:
    facts = EvidenceNormalizer().normalize(
        [
            {
                "subject_id": "author:an",
                "predicate": "AUTHORED",
                "object_id": "paper:bad",
                "value": {"name": "Bad", "sources": []},
                "paper_ids": ["paper:bad"],
                "source_url": "javascript:alert(1)",
                "year": 2024,
                "title": "Bad",
            }
        ]
    )
    assert facts == []
    assert build_citations(facts) == []


def test_citations_are_deduplicated_and_claim_linked() -> None:
    records = [
        {
            "subject_id": "author:an",
            "predicate": "AUTHORED",
            "object_id": "paper:rag",
            "value": {
                "name": "Graph Evidence for NLP",
                "sources": [
                    {
                        "paper_id": "paper:rag",
                        "title": "Graph Evidence for NLP",
                        "url": "https://example.org/papers/rag",
                    }
                ],
            },
            "paper_ids": ["paper:rag"],
            "source_url": "https://example.org/papers/rag",
            "year": 2024,
            "title": "Graph Evidence for NLP",
        }
    ]
    facts = EvidenceNormalizer().normalize(records)
    citations = build_citations([facts[0], facts[0]])
    assert len(citations) == 1
    assert citations[0].paper_id == "paper:rag"
    assert citations[0].claim_ids == [facts[0].fact_id]
