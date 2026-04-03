from __future__ import annotations

import unicodedata
from types import SimpleNamespace

from extensions import db
from models import HomeStatCard


HOMEPAGE_FIXED_STAT_SLOTS = (
    {
        "key": "toplam_malzeme",
        "metric_key": "total_assets",
        "title": "Toplam Malzeme",
        "default_image_url": "/static/img/sayisal-ozet/simge_1_malzeme.png",
        "default_alt": "Toplam Malzeme simgesi",
        "keywords": ("malzeme", "ekipman", "envanter", "asset", "stok"),
    },
    {
        "key": "toplam_personel",
        "metric_key": "total_personnel",
        "title": "Toplam Personel",
        "default_image_url": "/static/img/sayisal-ozet/simge_2_personel.png",
        "default_alt": "Toplam Personel simgesi",
        "keywords": ("personel", "kullanici", "kullanıcı", "gonullu", "gönüllü", "ekip"),
    },
    {
        "key": "aktif_tim",
        "metric_key": "total_airports",
        "title": "Aktif Tim",
        "default_image_url": "/static/img/sayisal-ozet/simge_3_aktif_tim.png",
        "default_alt": "Aktif Tim simgesi",
        "keywords": ("tim", "aktif", "havalimani", "havalimanı", "lokasyon", "birim"),
    },
    {
        "key": "tamamlanan_egitimler",
        "metric_key": "completed_trainings",
        "title": "Tamamlanan Eğitimler",
        "default_image_url": "/static/img/sayisal-ozet/simge_4_egitim.png",
        "default_alt": "Tamamlanan Eğitimler simgesi",
        "keywords": ("egitim", "eğitim", "tatbikat", "calisma", "çalışma", "modul", "modül"),
    },
)

HOMEPAGE_FIXED_STAT_KEYS = tuple(slot["key"] for slot in HOMEPAGE_FIXED_STAT_SLOTS)


def _normalize_text(value):
    text = str(value or "").strip().lower()
    text = text.translate(str.maketrans("çğıöşü", "cgiosu"))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(text.split())


def _safe_text(value, fallback=""):
    text = str(value or "").strip()
    return text if text else fallback


def _sorted_cards(cards):
    return sorted(cards or [], key=lambda item: (item.order_index or 0, item.id or 0))


def _card_match_score(card, slot):
    text = _normalize_text(f"{card.title or ''} {card.subtitle or ''}")
    title = _normalize_text(card.title)
    slot_title = _normalize_text(slot["title"])
    if title and title == slot_title:
        return 100
    score = 0
    for keyword in slot["keywords"]:
        if _normalize_text(keyword) in text:
            score += 1
    return score


def _arrange_cards_for_slots(cards):
    remaining = _sorted_cards(cards)
    assigned = [None] * len(HOMEPAGE_FIXED_STAT_SLOTS)

    for index in range(len(HOMEPAGE_FIXED_STAT_SLOTS)):
        by_order = [card for card in remaining if (card.order_index or 0) == index]
        if by_order:
            selected = by_order[0]
            assigned[index] = selected
            remaining.remove(selected)

    for index, slot in enumerate(HOMEPAGE_FIXED_STAT_SLOTS):
        if assigned[index] is not None:
            continue
        ranked = sorted(
            ((card, _card_match_score(card, slot)) for card in remaining),
            key=lambda pair: pair[1],
            reverse=True,
        )
        if ranked and ranked[0][1] > 0:
            selected = ranked[0][0]
            assigned[index] = selected
            remaining.remove(selected)

    for index in range(len(HOMEPAGE_FIXED_STAT_SLOTS)):
        if assigned[index] is None and remaining:
            assigned[index] = remaining.pop(0)

    return assigned


def ensure_fixed_homepage_stat_cards(existing_cards=None):
    cards = existing_cards
    if cards is None:
        cards = HomeStatCard.query.order_by(HomeStatCard.order_index.asc(), HomeStatCard.id.asc()).all()

    arranged = _arrange_cards_for_slots(cards)
    normalized = []
    changed = False

    for index, slot in enumerate(HOMEPAGE_FIXED_STAT_SLOTS):
        card = arranged[index]
        if card is None:
            card = HomeStatCard(
                title=slot["title"],
                value_text="0",
                subtitle=slot["default_alt"],
                icon=slot["default_image_url"],
                order_index=index,
                is_active=True,
            )
            db.session.add(card)
            normalized_value = "0"
            normalized_subtitle = slot["default_alt"]
            normalized_icon = slot["default_image_url"]
            changed = True
        else:
            normalized_value = _safe_text(card.value_text, "0")
            normalized_subtitle = _safe_text(card.subtitle, slot["default_alt"])
            normalized_icon = _safe_text(card.icon, slot["default_image_url"])

        if card.title != slot["title"]:
            card.title = slot["title"]
            changed = True
        if card.value_text != normalized_value:
            card.value_text = normalized_value
            changed = True
        if card.subtitle != normalized_subtitle:
            card.subtitle = normalized_subtitle
            changed = True
        if card.icon != normalized_icon:
            card.icon = normalized_icon
            changed = True
        if (card.order_index or 0) != index:
            card.order_index = index
            changed = True
        if card.is_active is not True:
            card.is_active = True
            changed = True

        normalized.append(card)

    return normalized, changed


def build_fixed_homepage_stat_payload(cards):
    arranged = _arrange_cards_for_slots(cards)
    payload = []

    for index, slot in enumerate(HOMEPAGE_FIXED_STAT_SLOTS):
        card = arranged[index]
        payload.append(
            SimpleNamespace(
                id=(card.id if card else None),
                slot_key=slot["key"],
                metric_key=slot["metric_key"],
                title=slot["title"],
                value_text=_safe_text(card.value_text if card else "", "0"),
                image_url=_safe_text(card.icon if card else "", slot["default_image_url"]),
                image_alt_text=_safe_text(card.subtitle if card else "", slot["default_alt"]),
                order_index=index,
            )
        )

    return payload
