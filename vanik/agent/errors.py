"""User-facing error and prompt messages, English and Hindi."""

from __future__ import annotations

_MESSAGES: dict[str, dict[str, str]] = {
    "needs_clarification_both": {
        "en": (
            "I need a bit more to work with. Could you tell me where the goods are "
            "coming from and where they're headed? For example: "
            "'ceramic tiles from India to the UK'."
        ),
        "hi": (
            "मुझे थोड़ी और जानकारी चाहिए। कृपया बताएं कि सामान कहाँ से आ रहा है "
            "और कहाँ जा रहा है? उदाहरण: 'भारत से UK को सिरेमिक टाइलें'।"
        ),
    },
    "needs_clarification_origin": {
        "en": (
            "Could you tell me where the goods are being exported from? "
            "For example: 'from India' or 'made in China'."
        ),
        "hi": (
            "कृपया बताएं कि सामान कहाँ से निर्यात हो रहा है? "
            "उदाहरण: 'भारत से' या 'चीन में बना'।"
        ),
    },
    "needs_clarification_destination": {
        "en": (
            "Could you tell me where the goods are being imported to? "
            "For example: 'to the UK', 'entering the EU', or 'into India'."
        ),
        "hi": (
            "कृपया बताएं कि सामान कहाँ आयात हो रहा है? "
            "उदाहरण: 'UK को', 'EU में', या 'भारत में'।"
        ),
    },
    "upstream_error_all": {
        "en": (
            "Tariff data is temporarily unavailable for all three corridors "
            "(UK, EU, India). This is usually a brief network issue — "
            "please try again in a moment."
        ),
        "hi": (
            "सभी तीन गलियारों (UK, EU, भारत) के लिए टैरिफ डेटा अभी उपलब्ध नहीं है। "
            "यह आमतौर पर एक अस्थायी नेटवर्क समस्या है — "
            "कृपया कुछ देर बाद पुनः प्रयास करें।"
        ),
    },
    "upstream_error_partial": {
        "en": "Rates for {corridors} could not be retrieved (timeout or API error).",
        "hi": "{corridors} के लिए दरें प्राप्त नहीं हो सकीं (टाइमआउट या API त्रुटि)।",
    },
    "no_match": {
        "en": (
            "I couldn't find a matching commodity code for that product. "
            "Try a simpler term (e.g. 'ceramic tiles' instead of 'floor covering material'), "
            "or enter a 6, 8, or 10-digit HS code directly."
        ),
        "hi": (
            "उस उत्पाद के लिए कोई मिलता-जुलता कमोडिटी कोड नहीं मिला। "
            "एक सरल शब्द आज़माएं (जैसे 'सिरेमिक टाइलें') "
            "या सीधे 6, 8, या 10-अंकीय HS कोड दर्ज करें।"
        ),
    },
    "gate_prompt": {
        "en": (
            "I found a few possible commodity codes for your product. "
            "Please select the best match by entering its number, "
            "or enter a 6, 8, or 10-digit code directly."
        ),
        "hi": (
            "आपके उत्पाद के लिए कुछ संभावित कमोडिटी कोड मिले। "
            "कृपया संख्या दर्ज करके सबसे उपयुक्त विकल्प चुनें, "
            "या सीधे 6, 8, या 10-अंकीय कोड दर्ज करें।"
        ),
    },
    "invalid_hs_format": {
        "en": "'{code}' is not a valid HS code. Please enter a 6, 8, or 10-digit numeric code.",
        "hi": "'{code}' एक मान्य HS कोड नहीं है। कृपया 6, 8, या 10-अंकीय संख्यात्मक कोड दर्ज करें।",
    },
    "invalid_gate_selection": {
        "en": (
            "That selection wasn't recognised. Please enter the option number "
            "or a 6, 8, or 10-digit commodity code."
        ),
        "hi": (
            "वह चयन पहचाना नहीं गया। कृपया विकल्प संख्या दर्ज करें "
            "या 6, 8, या 10-अंकीय कमोडिटी कोड।"
        ),
    },
    "extraction_service_unavailable": {
        "en": (
            "The extraction service is temporarily unavailable "
            "(API configuration error). Please contact support."
        ),
        "hi": (
            "एक्सट्रैक्शन सेवा अभी अनुपलब्ध है "
            "(API कॉन्फ़िगरेशन त्रुटि)। कृपया सहायता से संपर्क करें।"
        ),
    },
}


def msg(key: str, lang: str = "en", **kwargs: str) -> str:
    """Return user-facing message for key in given language, falling back to English."""
    bucket = _MESSAGES.get(key, {})
    text = bucket.get(lang) or bucket.get("en") or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text
