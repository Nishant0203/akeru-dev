from nes.v2_ner import extract_v2


def test_ms_v2_extracts_hs() -> None:
    entities = extract_v2("check 8708301090 into uk")
    assert entities["hs_code_provided"] == "8708301090"
