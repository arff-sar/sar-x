import unicodedata


_TR_UPPER_MAP = str.maketrans({"i": "İ", "ı": "I"})
_TR_LOOKUP_MAP = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "I": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }
)


def turkish_upper(value):
    text = str(value or "").strip()
    if not text:
        return ""
    return text.translate(_TR_UPPER_MAP).upper()


def normalize_lookup_key(value):
    text = str(value or "").strip()
    if not text:
        return ""
    translated = text.translate(_TR_LOOKUP_MAP).casefold()
    normalized = unicodedata.normalize("NFKD", translated)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).strip()


def turkish_equals(left, right):
    return normalize_lookup_key(left) == normalize_lookup_key(right)


def turkish_contains(haystack, needle):
    normalized_needle = normalize_lookup_key(needle)
    if not normalized_needle:
        return True
    return normalized_needle in normalize_lookup_key(haystack)


def turkish_contains_all(haystack, needle):
    normalized_terms = normalize_lookup_key(needle).split()
    if not normalized_terms:
        return True
    normalized_haystack = normalize_lookup_key(haystack)
    return all(term in normalized_haystack for term in normalized_terms)
