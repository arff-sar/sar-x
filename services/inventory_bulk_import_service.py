from datetime import datetime, date

from services.text_normalization_service import normalize_lookup_key, turkish_upper


TRUE_VALUES = {"1", "true", "t", "yes", "y", "evet", "e", "x", "✓", "on"}
FALSE_VALUES = {"0", "false", "f", "no", "n", "hayir", "hayır", "off", ""}


def parse_flexible_bool(value):
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    raise ValueError("Boolean alanı için geçersiz değer.")


def parse_flexible_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError("Tarih formatı geçersiz. Beklenen: YYYY-MM-DD")


def to_int(value, *, default=0, min_value=None):
    if value in (None, ""):
        return default
    parsed = int(value)
    if min_value is not None and parsed < min_value:
        raise ValueError(f"Değer en az {min_value} olmalıdır.")
    return parsed


def normalize_person_name(value):
    return turkish_upper(value)


def normalize_lookup(value):
    return normalize_lookup_key(value)

