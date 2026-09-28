from xml.etree.ElementTree import Element, SubElement, ElementTree

import pytest

from mascope.corpus import accepted_pairs, plain_text
from mascope.pipeline import prepare_corpus


def fixture(path, parent="1"):
    root = Element("posts")
    SubElement(root, "row", Id="2", PostTypeId="2", ParentId=parent,
               Body="<p>Use <code>a &lt; b</code>.</p>", Score="7",
               OwnerUserId="9", ContentLicense="CC BY-SA 4.0",
               CreationDate="2020-01-01", LastEditDate="2024-01-01")
    SubElement(root, "row", Id="1", PostTypeId="1", AcceptedAnswerId="2",
               Body="<p>" + " ".join(f"word{i}" for i in range(85)) + "</p>",
               Title="A test", Tags="<python><sorting>", OwnerUserId="8",
               ContentLicense="CC BY-SA 3.0", CreationDate="2017-01-01")
    SubElement(root, "row", Id="3", PostTypeId="2", ParentId="1",
               Body="<p>Unaccepted answer</p>", Score="20")
    SubElement(root, "row", Id="4", PostTypeId="1", AcceptedAnswerId="5",
               Body="<p>Too short</p>", Tags="<python>")
    SubElement(root, "row", Id="5", PostTypeId="2", ParentId="4",
               Body="<p>Another answer</p>")
    ElementTree(root).write(path, encoding="utf-8")


def test_accepted_pairs_join_filter_and_provenance(tmp_path):
    path = tmp_path / "Posts.xml"
    fixture(path)
    rows = list(accepted_pairs(path, tmp_path / "join.db", "stackoverflow", "2025-06-30"))
    assert len(rows) == 1
    assert rows[0]["answer_id"] == 2
    assert rows[0]["text"] == "Use a < b."
    result = prepare_corpus(rows, "stackoverflow", b"x" * 32)
    source = result["records"][0]
    assert source["question_license"] == "CC BY-SA 3.0"
    assert source["revision_date"] == "2024-01-01"
    assert source["source_snapshot"] == "2025-06-30"
    assert source["answer_score"] == 7
    assert "attribution" not in source
    assert "question_attribution" not in source
    assert result["attribution"][0]["attribution"]["user_id"] == "9"
    assert result["attribution"][0]["question_attribution"]["user_id"] == "8"


def test_accepted_pairs_rejects_wrong_parent_and_existing_database(tmp_path):
    path = tmp_path / "Posts.xml"
    fixture(path, parent="999")
    database = tmp_path / "join.db"
    rejected = []
    assert list(accepted_pairs(path, database, "stackoverflow", "2025-06-30", rejected)) == []
    assert rejected == [{"question_id": 1, "answer_id": 2, "reason": "accepted_answer_parent_mismatch", "parent_id": "999"}]
    with pytest.raises(FileExistsError):
        list(accepted_pairs(path, database, "stackoverflow", "2025-06-30"))


def test_plain_text_preserves_code_and_separates_blocks():
    assert plain_text("<p>a</p><pre>x &lt; 3</pre><p>b</p>") == "a\n\nx < 3\n\nb"


def test_shared_accepted_id_keeps_only_its_actual_parent(tmp_path):
    from xml.etree.ElementTree import parse

    path = tmp_path / "Posts.xml"
    fixture(path)
    tree = parse(path)
    root = tree.getroot()
    question = dict(next(row.attrib for row in root if row.get("Id") == "1"))
    question["Id"] = "6"
    SubElement(root, "row", **question)
    tree.write(path, encoding="utf-8")
    rejected = []
    records = list(accepted_pairs(path, tmp_path / "join.db", "stackoverflow", "2025-06-30", rejected))
    assert [row["question_id"] for row in records] == [1]
    assert [row["question_id"] for row in rejected] == [6]


def test_agent_receives_question_title_and_answer_without_author_metadata():
    from mascope.environment import Environment

    record = {"evidence_id": "MS-000000000001", "title": "Timeout setting",
              "question": "A request stalls for 30 seconds.", "text": "Check the upstream service.",
              "attribution": {"user_id": "42"}}
    passage = Environment._passages([record])[0]
    assert passage == {"evidence_id": record["evidence_id"],
                       "title": "Timeout setting\nA request stalls for 30 seconds.",
                       "text": record["text"]}
