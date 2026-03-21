"""Static reference for trade preference schemes (EU/UK) by origin–destination pair.

Real procurement should verify against current legal texts; this surfaces *why*
corridor switching can beat headline MFN for developing-country origins.
"""

from __future__ import annotations

# (origin ISO2, destination market) -> scheme metadata
PREFERENCE_SCHEMES: dict[tuple[str, str], dict[str, str]] = {
    # EU
    ("BD", "EU"): {
        "scheme": "EBA",
        "effective_note": "Everything But Arms — LDC, often 0% vs MFN",
        "typical_duty_vs_mfn": "preferential",
    },
    ("KH", "EU"): {
        "scheme": "EBA",
        "effective_note": "Everything But Arms — LDC",
        "typical_duty_vs_mfn": "preferential",
    },
    ("PK", "EU"): {
        "scheme": "GSP+",
        "effective_note": "GSP+ — enhanced preferences; many textiles at 0%",
        "typical_duty_vs_mfn": "preferential",
    },
    ("VN", "EU"): {
        "scheme": "EVFTA",
        "effective_note": "EU-Vietnam FTA — product-specific reductions",
        "typical_duty_vs_mfn": "mixed",
    },
    ("LK", "EU"): {
        "scheme": "GSP",
        "effective_note": "Standard GSP — reduced or zero on many lines",
        "typical_duty_vs_mfn": "preferential",
    },
    # UK (illustrative DCTS labels)
    ("BD", "GB"): {
        "scheme": "DCTS-EHC",
        "effective_note": "UK Enhanced Preferences — zero/lower on many goods",
        "typical_duty_vs_mfn": "preferential",
    },
    ("PK", "GB"): {
        "scheme": "DCTS-GDP",
        "effective_note": "UK DCTS General Framework — often reduced vs MFN",
        "typical_duty_vs_mfn": "preferential",
    },
    ("KH", "GB"): {
        "scheme": "DCTS-EHC",
        "effective_note": "UK Enhanced Preferences",
        "typical_duty_vs_mfn": "preferential",
    },
}


def get_preference_scheme(origin: str, destination: str) -> dict | None:
    o = (origin or "").strip().upper()[:2]
    d = (destination or "").strip().upper()
    if d == "UK":
        d = "GB"
    return PREFERENCE_SCHEMES.get((o, d))


def effective_duty_pct(
    mfn_rate_pct: float | None,
    origin: str,
    destination: str,
    *,
    assume_zero_if_preferential: bool = True,
) -> tuple[float | None, str]:
    """
    Return (effective_duty_pct, basis_label).

    When a known preferential scheme exists and ``assume_zero_if_preferential``,
    model **0%** for demo purposes for EBA/GSP+ style rows (user-facing insight).
    """
    if mfn_rate_pct is None:
        return None, "unknown"
    pref = get_preference_scheme(origin, destination)
    if pref and assume_zero_if_preferential:
        sch = pref.get("scheme", "")
        if sch in {"EBA", "GSP+"} or (sch.startswith("DCTS") and "EHC" in sch):
            return 0.0, f"preferential ({sch})"
        if sch == "DCTS-GDP":
            return max(0.0, float(mfn_rate_pct) * 0.5), f"illustrative half-MFN ({sch})"
    return float(mfn_rate_pct), "MFN"
