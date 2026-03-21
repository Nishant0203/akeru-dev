"""100 synthetic purchase orders for batch + corridor demo (no real customer data)."""

from __future__ import annotations

from typing import Any


def _r(
    po: str,
    product: str,
    origin: str,
    destination: str,
    *,
    hs_code: str | None = None,
    quantity: float = 1.0,
    unit_value_usd: float | None = None,
    incoterm: str = "FOB",
    notes: str | None = None,
    tags: list[str] | None = None,
    flags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "po": po,
        "product": product,
        "origin": origin,
        "destination": destination,
        "hs_code": hs_code,
        "quantity": quantity,
        "unit_value_usd": unit_value_usd,
        "incoterm": incoterm,
        "notes": notes,
        "tags": tags or [],
        "flags": flags or [],
    }


def build_demo_pos() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    # PO-001–010 — cotton garments, IN→GB/EU mix, FOB/CIF
    for i in range(1, 11):
        dest = "GB" if i % 2 else "EU"
        inc = "CIF" if i in (3, 7) else "FOB"
        uv = 11.8 + (i * 0.07)
        rows.append(
            _r(
                f"PO-{i:03d}",
                "cotton shirts woven",
                "IN",
                dest,
                quantity=800.0 + i * 50,
                unit_value_usd=round(uv, 2),
                incoterm=inc,
                tags=["garment", "cotton"],
            )
        )

    # PO-011–020 — automotive
    auto = [
        ("brake callipers passenger car", "8708301090", 24.5),
        ("alternator assembly 12V", "85115000", 180.0),
        ("shock absorber front axle", "87088099", 62.0),
        ("fuel injector diesel", "84099990", 45.0),
        ("windshield wiper motor", "85013100", 18.0),
        ("LED headlamp unit", "85122000", 210.0),
        ("rubber door seal extrusion", "40169300", 3.2),
        ("steel wheel rim 16 inch", "87087050", 55.0),
        ("catalytic converter substrate", "84213920", 320.0),
        ("ECU engine control unit", "90328900", 410.0),
    ]
    for j, (name, hs, uv) in enumerate(auto, start=11):
        rows.append(
            _r(
                f"PO-{j:03d}",
                name,
                "IN",
                "GB",
                hs_code=hs,
                quantity=120.0,
                unit_value_usd=uv,
                tags=["automotive"],
            )
        )

    # PO-021–025 — steel (often low/zero MFN UK)
    steel = [
        ("hot rolled coil 2mm S355", "720839", 640.0),
        ("galvanised sheet DX51", "721049", 710.0),
        ("stainless bar 304", "722100", 4200.0),
        ("wire rod 5.5mm", "721391", 580.0),
        ("rebar B500B", "721420", 495.0),
    ]
    for j, (name, hs, uv) in enumerate(steel, start=21):
        rows.append(
            _r(
                f"PO-{j:03d}",
                name,
                "IN",
                "EU",
                hs_code=hs,
                quantity=40.0,
                unit_value_usd=uv,
                tags=["steel"],
            )
        )

    # PO-026–030 — pharmaceuticals
    pharma = [
        ("paracetamol tablets BP 500mg", "30049099", 1.85),
        ("amoxicillin capsules", "30041000", 3.4),
        ("insulin injection pens", "30043100", 95.0),
        ("vaccine cold chain carrier", "902789", 2200.0),
        ("surgical gloves nitrile", "40151200", 8.5),
    ]
    for j, (name, hs, uv) in enumerate(pharma, start=26):
        rows.append(
            _r(
                f"PO-{j:03d}",
                name,
                "IN",
                "GB",
                hs_code=hs,
                quantity=5000.0,
                unit_value_usd=uv,
                tags=["pharma"],
            )
        )

    # PO-031–040 — electronics
    for j in range(31, 41):
        rows.append(
            _r(
                f"PO-{j:03d}",
                f"USB-C cable assembly batch {j - 30}",
                "CN",
                "GB",
                hs_code="85444290",
                quantity=10000.0,
                unit_value_usd=0.85 + (j - 31) * 0.02,
                tags=["electronics"],
            )
        )

    # PO-041–050 — textiles other
    tex = [
        ("polyester knitted fabric", "60063200", 4.2),
        ("denim fabric 12oz", "52094200", 6.8),
        ("silk scarves printed", "62141000", 22.0),
        ("wool blanket throws", "63012000", 38.0),
        ("towel set cotton terry", "63026000", 14.5),
        ("curtain blackout lining", "63039200", 9.9),
        ("lace trim nylon", "58041000", 1.1),
        ("canvas tote bags", "42029298", 3.4),
        ("sleeping bag synthetic", "94043000", 28.0),
        ("yoga mat TPE", "95069990", 6.0),
    ]
    for j, (name, hs, uv) in enumerate(tex, start=41):
        rows.append(
            _r(
                f"PO-{j:03d}",
                name,
                "IN",
                "EU" if j % 2 else "GB",
                hs_code=hs,
                quantity=600.0,
                unit_value_usd=uv,
                tags=["textile"],
            )
        )

    # PO-051–060 — food
    food = [
        ("basmati rice 1121 extra long", "10063020", 1.05),
        ("black tea bags bulk", "09023000", 4.6),
        ("mango pulp aseptic", "08045090", 2.8),
        ("frozen shrimp peeled", "03061700", 9.2),
        ("spices mix garam masala", "09109190", 5.5),
        ("jaggery organic blocks", "17029050", 1.9),
        ("pickle mango jar", "20019097", 2.2),
        ("ghee clarified butter", "04059020", 6.8),
        ("chickpea flour besan", "11061000", 0.95),
        ("coconut oil virgin", "15131900", 3.4),
    ]
    for j, (name, hs, uv) in enumerate(food, start=51):
        rows.append(
            _r(
                f"PO-{j:03d}",
                name,
                "IN",
                "GB",
                hs_code=hs,
                quantity=2000.0,
                unit_value_usd=uv,
                tags=["food"],
            )
        )

    # PO-061–070 — machinery
    for j in range(61, 71):
        rows.append(
            _r(
                f"PO-{j:03d}",
                f"industrial gearbox ratio 1:{10 + j - 61}",
                "DE",
                "IN",
                hs_code="84834000",
                quantity=3.0,
                unit_value_usd=12500.0 + (j - 61) * 800,
                incoterm="FCA",
                tags=["machinery", "import_in"],
            )
        )

    # PO-071–080 — plastics, ceramics, leather, footwear, jewellery, furniture, bedding
    misc = [
        (71, "injection moulded crate HDPE", "39231000", "IN", "GB", 12.5),
        (72, "PVC pipe 110mm", "39172300", "IN", "EU", 8.2),
        (73, "PET preforms 28mm", "39233000", "IN", "GB", 0.08),
        (74, "ceramic wall tiles 30x60", "69072100", "IN", "GB", 5.6),
        (75, "porcelain dinner set", "69111000", "IN", "EU", 42.0),
        (76, "leather handbags", "42022100", "IN", "GB", 38.0),
        (77, "synthetic upper footwear", "64039998", "VN", "EU", 14.2),
        (78, "gold plated necklace", "71131900", "IN", "GB", 120.0),
        (79, "wooden dining chair oak", "94016100", "IN", "GB", 85.0),
        (80, "fitted bedsheet cotton", "63023100", "IN", "EU", 11.0),
    ]
    for j, name, hs, o, d, uv in misc:
        rows.append(
            _r(f"PO-{j:03d}", name, o, d, hs_code=hs, quantity=250.0, unit_value_usd=uv, tags=["misc"])
        )

    # PO-081–085 — furniture, home, sport
    tail = [
        (81, "office desk melamine", "94033000", 195.0),
        (82, "LED floor lamp", "94051100", 48.0),
        (83, "bicycle helmet CE", "65061080", 22.0),
        (84, "dumbbell set rubber", "95069990", 55.0),
        (85, "camping tent 4-person", "63062200", 120.0),
    ]
    for j, name, hs, uv in tail:
        rows.append(
            _r(
                f"PO-{j:03d}",
                name,
                "IN",
                "GB",
                hs_code=hs,
                quantity=80.0,
                unit_value_usd=uv,
                tags=["furniture", "sport"],
            )
        )

    # PO-086–087 — DDP (duty paid by seller — rate for verification)
    rows.append(
        _r(
            "PO-086",
            "industrial pumps centrifugal",
            "DE",
            "IN",
            hs_code="84137099",
            quantity=2.0,
            unit_value_usd=8900.0,
            incoterm="DDP",
            notes="Duty included in price — tariff shown for verification only",
            flags=["ddp"],
            tags=["machinery"],
        )
    )
    rows.append(
        _r(
            "PO-087",
            "laboratory centrifuge",
            "US",
            "IN",
            hs_code="84211900",
            quantity=1.0,
            unit_value_usd=24000.0,
            incoterm="DDP",
            notes="DDP Mumbai — rate informational",
            flags=["ddp"],
            tags=["lab"],
        )
    )

    # PO-088–090 — fill to 90
    for j in range(88, 91):
        rows.append(
            _r(
                f"PO-{j:03d}",
                f"fasteners stainless M8 batch {j}",
                "IN",
                "EU",
                hs_code="73181588",
                quantity=5000.0,
                unit_value_usd=0.12,
                tags=["hardware"],
            )
        )

    # PO-091–095 — world → India (high value row)
    rows.append(
        _r(
            "PO-091",
            "aircraft engine parts CFM56",
            "US",
            "IN",
            hs_code="84119100",
            quantity=1.0,
            unit_value_usd=2_800_000.0,
            incoterm="CIF",
            tags=["aviation", "import_in"],
        )
    )
    extra_in = [
        (92, "precision bearings", "JP", "84821090", 45.0, 100.0),
        (93, "LCD display panel 15in", "KR", "85249200", 62.0, 100.0),
        (94, "copper cathodes", "CL", "74031100", 8850.0, 20.0),
        (95, "wine bottles Bordeaux", "FR", "22042178", 8.5, 100.0),
    ]
    for j, name, o, hs, uv, qty in extra_in:
        rows.append(
            _r(
                f"PO-{j:03d}",
                name,
                o,
                "IN",
                hs_code=hs,
                quantity=qty,
                unit_value_usd=uv,
                tags=["import_in"],
            )
        )

    # PO-096–098 — ambiguous (disambiguation)
    rows.append(
        _r(
            "PO-096",
            "cotton",
            "IN",
            "GB",
            quantity=1.0,
            unit_value_usd=5000.0,
            flags=["ambiguous"],
            tags=["disambiguation"],
        )
    )
    rows.append(
        _r(
            "PO-097",
            "parts for industrial machine",
            "IN",
            "EU",
            quantity=10.0,
            unit_value_usd=200.0,
            flags=["ambiguous"],
            tags=["disambiguation"],
        )
    )
    rows.append(
        _r(
            "PO-098",
            "steel",
            "IN",
            "GB",
            quantity=40.0,
            unit_value_usd=900.0,
            flags=["ambiguous"],
            tags=["disambiguation"],
        )
    )

    # PO-099–100 — typos (spell correction path)
    rows.append(
        _r(
            "PO-099",
            "coton shirts woven",
            "IN",
            "GB",
            quantity=1000.0,
            unit_value_usd=12.0,
            flags=["typo"],
            tags=["garment"],
        )
    )
    rows.append(
        _r(
            "PO-100",
            "brake callipars automotive",
            "IN",
            "GB",
            hs_code="8708301090",
            quantity=200.0,
            unit_value_usd=22.0,
            flags=["typo"],
            tags=["automotive"],
        )
    )

    assert len(rows) == 100, len(rows)
    return rows


DEMO_POS: list[dict[str, Any]] = build_demo_pos()
