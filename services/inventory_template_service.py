SHEET_DATA = "VERI_GIRISI"
SHEET_LISTS = "LISTELER"
SHEET_HELP = "ACIKLAMA"

FIELD_SCHEMA = [
    {"key": "kayit_tipi", "label": "Kayıt Tipi", "excel": "kayıt_tipi", "numbered": True},
    {"key": "merkezi_sablon", "label": "Merkezi Şablon", "excel": "merkezi_sablon", "numbered": True},
    {"key": "merkezi_sablondan_olustur", "label": "Merkezi Şablondan Oluştur", "excel": "merkezi_sablondan_olustur"},
    {"key": "havalimani", "label": "Havalimanı", "excel": "havalimani", "required": True},
    {"key": "kategori", "label": "Kategori", "excel": "kategori", "required": True, "numbered": True},
    {"key": "malzeme_adi", "label": "Malzeme Adı", "excel": "malzeme_adi", "required": True, "numbered": True},
    {"key": "marka", "label": "Marka", "excel": "marka", "numbered": True},
    {"key": "model", "label": "Model", "excel": "model", "numbered": True},
    {"key": "demirbas_mi", "label": "Demirbaş mı?", "excel": "demirbas_mi", "numbered": True},
    {"key": "demirbas_no", "label": "Demirbaş Numarası", "excel": "demirbas_no"},
    {"key": "seri_no", "label": "Seri No", "excel": "seri_no", "numbered": True},
    {"key": "stok_birim_sayisi", "label": "Stok Birim Sayısı", "excel": "stok_birim_sayisi", "required": True, "numbered": True},
    {"key": "kullanim_durumu", "label": "Kullanım Durumu", "excel": "kullanim_durumu", "required": True, "numbered": True},
    {"key": "kalibrasyon_gerekli_mi", "label": "Kalibrasyon Gerekli mi?", "excel": "kalibrasyon_gerekli_mi", "numbered": True},
    {"key": "kalibrasyon_periyodu_ay", "label": "Kalibrasyon Periyodu (Ay)", "excel": "kalibrasyon_periyodu_ay"},
    {"key": "son_kalibrasyon_tarihi", "label": "Son Kalibrasyon Tarihi", "excel": "son_kalibrasyon_tarihi"},
    {"key": "sonraki_kalibrasyon_tarihi", "label": "Sonraki Kalibrasyon Tarihi", "excel": "sonraki_kalibrasyon_tarihi"},
    {"key": "bakim_formu", "label": "Bakım Formu", "excel": "bakim_formu", "numbered": True},
    {"key": "bakim_periyodu", "label": "Bakım Periyodu (Ay)", "excel": "bakim_periyodu", "numbered": True},
    {"key": "edinim_tarihi", "label": "Edinim Tarihi", "excel": "edinim_tarihi", "numbered": True},
    {"key": "garanti_bitis_tarihi", "label": "Garanti Bitiş Tarihi", "excel": "garanti_bitis_tarihi", "numbered": True},
    {"key": "kutu_kodu", "label": "Kutu Kodu", "excel": "kutu_kodu", "required": True, "numbered": True},
    {"key": "yedek_parca_baglantisi", "label": "Yedek Parça Bağlantısı", "excel": "yedek_parca_baglantisi"},
    {"key": "kullanim_kilavuzu_linki", "label": "Kullanım Kılavuzu Linki", "excel": "kullanim_kilavuzu_linki", "numbered": True},
    {"key": "teknik_ozellikler", "label": "Teknik Özellikler", "excel": "teknik_ozellikler"},
    {"key": "aciklama_notlar", "label": "Açıklama / Notlar", "excel": "aciklama_notlar", "numbered": True},
    {"key": "ad_soyad", "label": "Ad Soyad", "excel": "ad_soyad"},
]


def form_label_map():
    labels = {}
    counter = 1
    for item in FIELD_SCHEMA:
        label = item["label"]
        if item.get("numbered"):
            label = f"{counter}) {label}"
            counter += 1
        labels[item["key"]] = label
    return labels


def excel_headers():
    return [item["excel"] for item in FIELD_SCHEMA]


def required_excel_headers():
    return [item["excel"] for item in FIELD_SCHEMA if item.get("required")]

