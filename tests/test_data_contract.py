import copy
import json

import pytest

from src.common import sha256_file
from src.data.contracts import ContractError, load_dataset
from src.data.fixtures import fixture_tables, write_dataset
from src.data.normalize import Normalizer, author_position_label, invert_abstract, name_compatible


@pytest.fixture
def tables():
    return fixture_tables()


def _ds(tmp_path, tables):
    write_dataset(tmp_path, tables)
    return tmp_path


def test_fixture_valid(tmp_path, tables):
    rows = load_dataset(_ds(tmp_path, tables))
    assert len(rows["papers.jsonl"]) == 5


@pytest.mark.parametrize("mutate,needle", [
    (lambda t: t["papers.jsonl"].append(dict(t["papers.jsonl"][0])), "duplicate key"),
    (lambda t: t["papers.jsonl"][0].update(year=2019), "out of scope"),
    (lambda t: t["papers.jsonl"][0].update(title="  "), "blank title"),
    (lambda t: t["papers.jsonl"][1].update(doi=t["papers.jsonl"][0]["doi"]), "duplicate doi"),
    (lambda t: t["paper_authors.jsonl"].append({**t["paper_authors.jsonl"][0], "author_id": "oa:ANOPE", "position": 3}), "unknown author"),
    (lambda t: t["affiliations.jsonl"].append({**t["affiliations.jsonl"][0], "author_id": "oa:AFIX4"}), "is not an author of"),
    (lambda t: t["affiliations.jsonl"].append({**t["affiliations.jsonl"][0], "institution_id": "oa:I999"}), "unknown institution"),
    (lambda t: t["citations.jsonl"].append({"citing_paper_id": "oa:WFIX1", "cited_paper_id": "oa:WOUTSIDE", "source_url": "x"}), "outside corpus"),
    (lambda t: t["citations.jsonl"].append({"citing_paper_id": "oa:WFIX1", "cited_paper_id": "oa:WFIX1", "source_url": "x"}), "self-citation"),
    (lambda t: t["paper_topics.jsonl"].append({**t["paper_topics.jsonl"][0], "topic_id": "qa", "evidence_span": "not in text"}), "not in title/abstract"),
    (lambda t: t["paper_topics.jsonl"].append({**t["paper_topics.jsonl"][0], "topic_id": "nonsense"}), "topic_id"),
    (lambda t: t["papers.jsonl"][0].update(id="W123"), "namespace"),
])
def test_contract_violations(tmp_path, tables, mutate, needle):
    t = copy.deepcopy(tables)
    mutate(t)
    with pytest.raises(ContractError) as exc:
        load_dataset(_ds(tmp_path, t))
    assert any(needle in e for e in exc.value.errors), exc.value.errors[:5]


def test_manifest_tamper_detected(tmp_path, tables):
    d = _ds(tmp_path, tables)
    with open(d / "papers.jsonl", "a", encoding="utf-8") as fh:
        fh.write("\n")
    fh = d / "papers.jsonl"
    content = fh.read_text(encoding="utf-8").replace("Morphology", "Morphologies")
    fh.write_text(content, encoding="utf-8")
    with pytest.raises(ContractError) as exc:
        load_dataset(d)
    assert any("sha256" in e for e in exc.value.errors)


def test_missing_manifest(tmp_path, tables):
    d = _ds(tmp_path, tables)
    (d / "manifest.json").unlink()
    with pytest.raises(ContractError):
        load_dataset(d)


def test_helpers():
    assert invert_abstract({"world": [1], "hello": [0]}) == "hello world"
    assert author_position_label(1, 1) == "first"
    assert author_position_label(3, 3) == "last"
    assert author_position_label(2, 3) == "middle"
    assert name_compatible("Yajiao Liu", "Yajiao Liu")
    assert not name_compatible("Yajiao Liu", "John Smith")


def _acl(acl_id, title, authors, doi=None):
    return {"acl_id": acl_id, "paper_num": int(acl_id.rsplit(".", 1)[1]), "collection": "2024.acl", "volume": "long",
            "volume_title": "ACL 2024", "year": 2024, "title": title, "abstract": "abc", "doi": doi,
            "url": f"https://aclanthology.org/{acl_id}/",
            "authors": [{"position": i, "name": n, "acl_author_id": None, "orcid": None, "raw_affiliation": None}
                        for i, n in enumerate(authors, 1)], "source_kind": "acl"}


def _work(wid, names, aids, insts=None, refs=()):
    return {"id": f"https://openalex.org/{wid}", "referenced_works": [f"https://openalex.org/{r}" for r in refs],
            "authorships": [{"author": {"id": f"https://openalex.org/{a}", "display_name": n},
                             "institutions": [{"id": f"https://openalex.org/{insts[k]}", "display_name": insts[k]}] if insts and insts[k] else [],
                             "raw_affiliation_strings": []}
                            for k, (n, a) in enumerate(zip(names, aids))]}


def test_normalizer_identity_and_dedup():
    acl = [_acl("2024.acl-long.1", "Paper One About Translation", ["Ann Lee", "Bo Chen"], "10.1/a"),
           _acl("2024.acl-long.2", "Paper Two About Retrieval", ["Ann Lee", "Cy Diaz"], "10.1/b")]
    arx = [{"arxiv_id": "2401.00001", "title": "Paper One About Translation", "abstract": "x", "year": 2024,
            "primary_category": "cs.CL", "journal_doi": None, "url": "https://arxiv.org/abs/2401.00001",
            "authors": [{"position": 1, "name": "Ann Lee", "raw_affiliation": None}], "source_kind": "arxiv"},
           {"arxiv_id": "2401.00002", "title": "Unrelated Third Paper", "abstract": "y", "year": 2024,
            "primary_category": "cs.CL", "journal_doi": None, "url": "https://arxiv.org/abs/2401.00002",
            "authors": [{"position": 1, "name": "Ann Lee", "raw_affiliation": None}], "source_kind": "arxiv"}]
    oa = [{"source_kind": "acl", "source_id": "2024.acl-long.1",
           "openalex": _work("W1", ["Ann Lee", "Bo Chen"], ["A1", "A2"], ["I1", None])},
          {"source_kind": "acl", "source_id": "2024.acl-long.2",
           "openalex": _work("W2", ["Ann Lee", "Wrong Person"], ["A1", "A9"], refs=["W1", "W999", "W2"])},
          {"source_kind": "arxiv", "source_id": "2401.00001", "openalex": _work("W1", ["Ann Lee", "Bo Chen"], ["A1", "A2"])},
          {"source_kind": "arxiv", "source_id": "2401.00002", "openalex": None}]
    ents = Normalizer(acl, arx, oa).run()
    pids = sorted(p["id"] for p in ents["papers"])
    # preprint of W1 merged into ACL record; unmatched arXiv kept with source id
    assert pids == ["arxiv:2401.00002", "oa:W1", "oa:W2"]
    w1 = next(p for p in ents["papers"] if p["id"] == "oa:W1")
    assert w1["arxiv_id"] == "2401.00001" and w1["source_kind"] == "acl"
    a_ids = {a["id"]: a for a in ents["authors"]}
    # name mismatch at W2#2 -> scoped source-only, not linked to A9
    assert "oa:A9" not in a_ids and "src:oa:W2#2" in a_ids
    # same name "Ann Lee" on unmatched arXiv paper is NOT merged with oa:A1
    assert "src:arxiv:2401.00002#1" in a_ids
    # citations only inside corpus, correct direction, no self-cite
    assert ents["citations"] == [{"citing_paper_id": "oa:W2", "cited_paper_id": "oa:W1",
                                  "source_url": "https://openalex.org/W2"}]
    # per-paper affiliation only for the authorship that declares it
    assert [(a["paper_id"], a["author_id"], a["institution_id"]) for a in ents["affiliations"]] == [("oa:W1", "oa:A1", "oa:I1")]


def test_checksum_helper(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("abc", encoding="utf-8")
    assert sha256_file(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    json.dumps({})
