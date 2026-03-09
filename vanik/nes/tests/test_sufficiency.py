from nes.sufficiency import ner_is_sufficient


def test_sufficiency_flags_ambiguous_origin_candidates() -> None:
    ok, reason = ner_is_sufficient(
        {
            "product_terms": ["brake callipers"],
            "origin": None,
            "destination": "GB",
            "_origin_candidates": ["IN", "CN"],
        }
    )
    assert ok is False
    assert reason == "ambiguous_origin"


def test_sufficiency_flags_ambiguous_origin_list_field() -> None:
    ok, reason = ner_is_sufficient(
        {
            "product_terms": ["brake callipers"],
            "origin": ["IN", "CN"],
            "destination": "GB",
        }
    )
    assert ok is False
    assert reason == "ambiguous_origin"


def test_sufficiency_accepts_single_origin_candidate() -> None:
    ok, reason = ner_is_sufficient(
        {
            "product_terms": ["brake callipers"],
            "origin": "IN",
            "destination": "GB",
            "_origin_candidates": ["IN"],
        }
    )
    assert ok is True
    assert reason is None


def test_sufficiency_flags_partial_corridor_as_insufficient() -> None:
    ok, reason = ner_is_sufficient(
        {
            "product_terms": ["brake callipers"],
            "origin": "IN",
            "destination": None,
        }
    )
    assert ok is False
    assert reason == "no_corridor"
