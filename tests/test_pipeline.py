import pytest
from mascope.pipeline import prepare_corpus, minhash, freeze_family, release_gate


def test_corpus_filter_dedup_score_and_uniform_cap():
    text = " ".join("word" + str(i) for i in range(90))
    first = {
        "accepted": True,
        "question": text,
        "title": "Question",
        "tags": ["topic"],
        "text": "Answer",
        "question_id": 1,
        "answer_id": 2,
        "answer_score": 2,
        "attribution": {"name": "author"},
    }
    higher = {**first, "answer_id": 3, "answer_score": 5}
    short = {**first, "answer_id": 4, "question": "short"}
    not_accepted = {**first, "answer_id": 5, "accepted": False}
    result = prepare_corpus([first, higher, short, not_accepted], "site", b"a" * 32)
    assert result["counts"] == {
        "input": 4,
        "eligible": 2,
        "deduplicated": 1,
        "retained": 1,
    }
    assert result["records"][0]["answer_id"] == 3
    assert "attribution" not in result["records"][0]
    assert result["attribution"][0]["attribution"]["name"] == "author"
    assert result["profile_tags"] == ["topic"]
    assert minhash(text) == minhash(text)


def test_release_does_not_promote_reconstructed_counts_to_certification():
    with pytest.raises(ValueError, match="Only frozen"):
        release_gate(
            [{"family_id": "f", "disposition": "return_to_composition", "cell": "C2S1"}]
        )
    with pytest.raises(ValueError, match="construction gate"):
        freeze_family({"family_id": "f"}, {"disposition": "revise"})
