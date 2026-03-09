from nes.v2_ner import extract_v2


def test_ms_v2_extracts_hs() -> None:
    entities = extract_v2("check 8708301090 into uk")
    assert entities["hs_code_provided"] == "8708301090"


def test_ms_v2_detects_uk_as_destination() -> None:
    entities = extract_v2("duty on brake parts from india to uk")
    assert entities["origin"] == "IN"
    assert entities["destination"] == "GB"


def test_ms_v2_detects_uk_as_origin() -> None:
    entities = extract_v2("exports from britain to india")
    assert entities["origin"] == "GB"
    assert entities["destination"] == "IN"


def test_ms_v2_maps_eu_destinations_to_eu() -> None:
    entities = extract_v2("ceramic tiles from india to germany")
    assert entities["origin"] == "IN"
    assert entities["destination"] == "EU"


def test_ms_v2_uses_directional_prepositions() -> None:
    entities = extract_v2("made in china and importing into the uk")
    assert entities["origin"] == "CN"
    assert entities["destination"] == "GB"
