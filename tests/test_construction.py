import pytest

from mascope.construction import certify_dependencies, source_identifier


def test_private_source_ids_are_stable_and_keyed():
    first = source_identifier(b"a" * 32, "site", 42, 0)
    assert len(first) == 15 and first.startswith("MS-")
    assert first == source_identifier(b"a" * 32, "site", 42, 0)
    assert first != source_identifier(b"b" * 32, "site", 42, 0)
    assert first != source_identifier(b"a" * 32, "site", 42, 1)
    with pytest.raises(ValueError):
        source_identifier(b"", "site", 42, 0)


def test_certification_requires_exhaustive_actual_outcomes():
    full = {"a": [True] * 10, "b": [True] * 8 + [False] * 2}
    withheld = {("a", "b"): [True] + [False] * 9, ("b", "a"): [True] * 10}
    result = certify_dependencies(["a", "b"], full, withheld)
    assert result["edges"] == [{"from": "a", "to": "b"}]
    with pytest.raises(ValueError, match="Every ordered"):
        certify_dependencies(["a", "b"], full, {})
    withheld[("b", "a")] = [False] * 10
    with pytest.raises(ValueError, match="cycle"):
        certify_dependencies(["a", "b"], full, withheld)
