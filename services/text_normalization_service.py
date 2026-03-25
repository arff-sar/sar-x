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

