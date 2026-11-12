import pytest

from src.common import ROOT
from src.data.topics import TopicClassifier


@pytest.fixture(scope="module")
def clf():
    return TopicClassifier.from_file(ROOT / "configs" / "topics.yaml")


def ids(res):
    return [t["topic_id"] for t in res.topics]


def test_title_match_assigns(clf):
    r = clf.classify("Improving Machine Translation for Low-Resource Languages", "We propose a method.")
    assert ids(r) == ["mt"]
    assert r.topics[0]["evidence_span"] == "Machine Translation"


def test_abstract_only_single_hit_is_not_enough(clf):
    r = clf.classify("A New Method", "We also briefly discuss question answering.")
    assert r.status == "UNKNOWN" and ids(r) == []


def test_title_plus_abstract_two_topics(clf):
    r = clf.classify("Retrieval-Augmented Generation for Question Answering",
                     "We study retrieval-augmented generation for open-domain question answering.")
    assert sorted(ids(r)) == ["qa", "retrieval"]


def test_rag_whole_word_only(clf):
    r = clf.classify("Fragment parsing with Paragraph encoders", "fragrant ragged text")
    assert "retrieval" not in ids(r)
    r2 = clf.classify("RAG for clinical notes", "")
    assert ids(r2) == ["retrieval"]


def test_generic_words_do_not_fire(clf):
    r = clf.classify("A model for evaluation of summary statistics", "Our model gives a summary and an evaluation.")
    assert ids(r) == []


def test_max_two_and_tie_goes_to_review(clf):
    r = clf.classify("Machine Translation, Question Answering and Summarization with Large Language Models", "")
    assert r.status == "tie_review"
    assert len(r.topics) <= 2


def test_spans_come_from_text(clf):
    title = "Detecting Hallucinations in LLMs"
    r = clf.classify(title, "")
    for t in r.topics:
        assert t["evidence_span"].lower() in title.lower()


def test_unicode_normalisation(clf):
    r = clf.classify("Ｍachine　Translation of tweets", "")
    assert ids(r) == ["mt"]
