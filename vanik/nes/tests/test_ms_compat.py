from nes._legacy_extractor import extract_entities


def test_extract_hs_code() -> None:
    entities = extract_entities("check 8708301090 into UK")
    assert entities["hs_code_provided"] == "8708301090"
