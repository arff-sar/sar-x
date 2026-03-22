import json
from functools import wraps

from flask import abort, current_app, request, url_for
from flask_login import current_user
from extensions import table_exists

ROLE_OWNER = "sahip"
ROLE_SYSTEM_OWNER = "sistem_sahibi"
ROLE_ADMIN = "admin"
ROLE_EDITOR = "editor"
ROLE_MANAGER = "yetkili"
ROLE_AIRPORT_MANAGER = "havalimani_yoneticisi"
ROLE_MAINTENANCE = "bakim_sorumlusu"
ROLE_WAREHOUSE = "depo_sorumlusu"
ROLE_PERSONNEL = "personel"
ROLE_READONLY = "readonly"
ROLE_HQ = "genel_mudurluk"

ROLE_ALIASES = {
    ROLE_OWNER: ROLE_SYSTEM_OWNER,
    ROLE_SYSTEM_OWNER: ROLE_SYSTEM_OWNER,
    ROLE_MANAGER: ROLE_AIRPORT_MANAGER,
    ROLE_AIRPORT_MANAGER: ROLE_AIRPORT_MANAGER,
    ROLE_HQ: ROLE_READONLY,
    ROLE_READONLY: ROLE_READONLY,
    ROLE_EDITOR: ROLE_EDITOR,
    ROLE_ADMIN: ROLE_ADMIN,
    ROLE_MAINTENANCE: ROLE_MAINTENANCE,
    ROLE_WAREHOUSE: ROLE_WAREHOUSE,
    ROLE_PERSONNEL: ROLE_PERSONNEL,
}

ROLE_PRIORITY = {
    ROLE_SYSTEM_OWNER: 100,
    ROLE_ADMIN: 90,
    ROLE_AIRPORT_MANAGER: 70,
    ROLE_EDITOR: 60,
    ROLE_MAINTENANCE: 50,
    ROLE_WAREHOUSE: 45,
    ROLE_PERSONNEL: 30,
    ROLE_READONLY: 20,
}

DEFAULT_ROLE_LABELS = {
    ROLE_OWNER: "Sistem Sahibi",
    ROLE_ADMIN: "Yönetici",
    ROLE_EDITOR: "İçerik Editörü",
    ROLE_MANAGER: "Havalimanı Yöneticisi",
    ROLE_MAINTENANCE: "Bakım Sorumlusu",
    ROLE_WAREHOUSE: "Depo Sorumlusu",
    ROLE_PERSONNEL: "Personel",
    ROLE_READONLY: "İzleyici",
    ROLE_HQ: "Genel Müdürlük",
}

DEFAULT_ROLE_DESCRIPTIONS = {
    ROLE_OWNER: "Tüm modüller, kritik rol atamaları ve sistem yapılandırması üzerinde tam yetkiye sahiptir.",
    ROLE_ADMIN: "Kullanıcılar, roller, ayarlar ve operasyon modüllerini yönetebilir.",
    ROLE_EDITOR: "Anasayfa içerikleri, medya ve yayın akışlarını yönetebilir.",
    ROLE_MANAGER: "Kendi havalimanındaki operasyon, bakım, iş emri ve rapor ekranlarını yönetebilir.",
    ROLE_MAINTENANCE: "Bakım planları, iş emirleri ve bakım formlarını yönetebilir.",
    ROLE_WAREHOUSE: "Envanter, kutu içerikleri, stok ve yedek parça hareketlerini yönetebilir.",
    ROLE_PERSONNEL: "Saha ekipmanı görüntüleyebilir, checklist doldurabilir ve atanan işleri tamamlayabilir.",
    ROLE_READONLY: "Sadece görüntüleme yapabilir, veri değiştiremez.",
    ROLE_HQ: "Merkezi görünüm üzerinden rapor ve operasyon özetlerini izleyebilir.",
}

ROLE_OPTIONS = [
    {"key": ROLE_OWNER, "label": "Sistem Sahibi", "scope": "global", "critical": True},
    {"key": ROLE_ADMIN, "label": "Yönetici", "scope": "global", "critical": True},
    {"key": ROLE_EDITOR, "label": "İçerik Editörü", "scope": "global", "critical": False},
    {"key": ROLE_MANAGER, "label": "Havalimanı Yöneticisi", "scope": "airport", "critical": False},
    {"key": ROLE_MAINTENANCE, "label": "Bakım Sorumlusu", "scope": "airport", "critical": False},
    {"key": ROLE_WAREHOUSE, "label": "Depo Sorumlusu", "scope": "airport", "critical": False},
    {"key": ROLE_PERSONNEL, "label": "Personel", "scope": "airport", "critical": False},
    {"key": ROLE_READONLY, "label": "İzleyici", "scope": "global", "critical": False},
    {"key": ROLE_HQ, "label": "Genel Müdürlük", "scope": "global", "critical": False},
]

PERMISSION_MODULE_LABELS = {
    "dashboard": "Gösterge Paneli",
    "homepage": "İçerik Yönetimi",
    "inventory": "Envanter",
    "maintenance": "Bakım",
    "workorder": "İş Emirleri",
    "parts": "Parça ve Stok",
    "admin": "Yönetim",
    "reports": "Raporlama",
}


def _permission(key, label, module, summary, description=None):
    return {
        "key": key,
        "label": label,
        "module": module,
        "module_label": PERMISSION_MODULE_LABELS.get(module, module),
        "summary": summary,
        "description": description or summary,
    }


PERMISSION_DEFINITIONS = [
    _permission(
        "dashboard.view",
        "Gösterge Panelini Görüntüleme",
        "dashboard",
        "Dashboard ekranını ve özet operasyon metriklerini görebilir.",
        "Dashboard ekranı, kritik KPI kartları, uyarılar ve yönetici özet bloklarına erişebilir.",
    ),
    _permission(
        "homepage.view",
        "Anasayfa İçeriğini Görüntüleme",
        "homepage",
        "Anasayfa içerik kayıtlarını ve yayın durumlarını görebilir.",
        "Slider, bölüm, duyuru, doküman ve hızlı bağlantı kayıtlarını görüntüleyebilir.",
    ),
    _permission(
        "homepage.edit",
        "Anasayfa İçeriğini Düzenleme",
        "homepage",
        "Anasayfa içeriklerini oluşturabilir ve düzenleyebilir.",
        "Slider, bölüm, duyuru, doküman ve bağlantı kayıtlarında değişiklik yapabilir.",
    ),
    _permission(
        "homepage.publish",
        "Anasayfa İçeriğini Yayınlama",
        "homepage",
        "Taslak içerikleri yayına alabilir veya yayından kaldırabilir.",
        "Yayın akışındaki içeriklerin public anasayfada görünmesini doğrudan kontrol edebilir.",
    ),
    _permission(
        "homepage.media",
        "Medya Kütüphanesini Yönetme",
        "homepage",
        "Medya dosyalarını yükleyebilir, arşivleyebilir ve seçebilir.",
        "CMS ve anasayfa bileşenlerinde kullanılan görsel/doküman dosyalarını yönetebilir.",
    ),
    _permission(
        "inventory.view",
        "Envanteri Görüntüleme",
        "inventory",
        "Ekipman, kutu ve varlık kayıtlarını görüntüleyebilir.",
        "Envanter listesi, kutu detayları, asset kartları ve ilgili operasyon verilerini görebilir.",
    ),
    _permission(
        "inventory.create",
        "Envantere Kayıt Ekleme",
        "inventory",
        "Yeni ekipman, asset veya envanter kaydı oluşturabilir.",
        "Yeni fiziksel kayıtlar açabilir ve bunları ilgili havalimanı/kutu ile ilişkilendirebilir.",
    ),
    _permission(
        "inventory.edit",
        "Envanteri Düzenleme",
        "inventory",
        "Mevcut envanter kayıtlarını güncelleyebilir.",
        "Asset bilgileri, kutu içeriği, durum ve operasyonel alanlar üzerinde düzenleme yapabilir.",
    ),
    _permission(
        "inventory.delete",
        "Envanteri Arşivleme",
        "inventory",
        "Envanter kayıtlarını pasife alabilir veya arşive taşıyabilir.",
        "Aktif listelerden kaldırılan kayıtların geçmişini koruyarak arşiv işlemi yapabilir.",
    ),
    _permission(
        "inventory.export",
        "Envanteri Dışa Aktarma",
        "inventory",
        "Envanter listesini Excel, CSV veya PDF olarak dışa aktarabilir.",
        "Filtrelenmiş veya özet envanter verilerini güvenli export limitleri içinde dışarı alabilir.",
    ),
    _permission(
        "assignment.view",
        "Zimmet Kayıtlarını Görüntüleme",
        "inventory",
        "Zimmet listelerini, personel üzerindeki aktif kayıtları ve geçmişi görüntüleyebilir.",
        "Zimmet formları, personel üzerindeki malzeme kayıtları ve iade geçmişlerini görüntüleyebilir.",
    ),
    _permission(
        "assignment.create",
        "Zimmet Oluşturma",
        "inventory",
        "Tekli veya çoklu malzeme için yeni zimmet kaydı açabilir.",
        "Bir veya birden fazla malzemeyi bir veya birden fazla personele zimmetleyebilir.",
    ),
    _permission(
        "assignment.manage",
        "Zimmet İade ve Güncelleme",
        "inventory",
        "Zimmet kayıtlarını güncelleyebilir, iade ve kısmi iade işlemlerini işleyebilir.",
        "Aktif zimmetler üzerinde durum güncelleme, tam iade ve kısmi iade işlemlerini kayıt altına alabilir.",
    ),
    _permission(
        "assignment.pdf",
        "Zimmet PDF Alma",
        "inventory",
        "Kurumsal zimmet formunu PDF olarak üretebilir ve indirebilir.",
        "Zimmet formu için resmi PDF çıktısı alabilir ve yazdırma akışını başlatabilir.",
    ),
    _permission(
        "assignment.document.upload",
        "İmzalı Zimmet Belgesi Yükleme",
        "inventory",
        "Islak imzalı zimmet belgelerini sisteme yükleyebilir ve ilişkilendirebilir.",
        "İmzalı zimmet formu veya ilgili belgeyi zimmet kaydına ekleyebilir ve tekrar erişime açabilir.",
    ),
    _permission(
        "ppe.view",
        "KKD Kayıtlarını Görüntüleme",
        "inventory",
        "KKD tahsis kayıtlarını yetki kapsamına göre görüntüleyebilir.",
        "Personel bazlı kişisel koruyucu donanım kayıtlarını kendi yetki kapsamı içinde görüntüleyebilir.",
    ),
    _permission(
        "ppe.request",
        "KKD Bildirim ve Talep Oluşturma",
        "inventory",
        "Eksik, hasarlı, kayıp veya değişim talebi bildirimleri oluşturabilir.",
        "Kendi KKD kayıtları için eksik, hasarlı, kayıp, kullanım dışı veya değişim talebi bildirimleri açabilir.",
    ),
    _permission(
        "ppe.manage",
        "KKD Yönetimi",
        "inventory",
        "KKD tahsislerini oluşturabilir, güncelleyebilir ve raporlayabilir.",
        "Personel bazlı KKD teslimi, durum güncellemesi ve havalimanı bazlı raporlamayı yönetebilir.",
    ),
    _permission(
        "maintenance.view",
        "Bakım Modülünü Görüntüleme",
        "maintenance",
        "Bakım planları, geçmiş ve ilgili kayıtları görebilir.",
        "Yaklaşan/geciken bakım listeleri, bakım geçmişi ve bakım formlarını görüntüleyebilir.",
    ),
    _permission(
        "maintenance.edit",
        "Bakım Kaydı İşleme",
        "maintenance",
        "Bakım kaydı girebilir, checklist doldurabilir ve bakım akışını güncelleyebilir.",
        "Saha bakım formları, bakım geçmişi ve bakım sonucu verilerini işleyebilir.",
    ),
    _permission(
        "maintenance.plan.change",
        "Bakım Planını Değiştirme",
        "maintenance",
        "Bakım planı periyotlarını ve tetikleyicileri değiştirebilir.",
        "Periyodik bakım tarihleri, sayaç eşikleri ve aktif plan tanımlarını güncelleyebilir.",
    ),
    _permission(
        "maintenance.instructions.manage",
        "Bakım Talimatlarını Yönetme",
        "maintenance",
        "Ekipman tiplerine bağlı bakım talimatları, kılavuz ve görsel bilgilerini yönetebilir.",
        "Bakım talimatı, üretici linki, görsel ve revizyon bilgisini ekipman tipine göre güncelleyebilir.",
    ),
    _permission(
        "maintenance.templates.manage",
        "Kontrol Şablonlarını Yönetme",
        "maintenance",
        "Bakım kontrol şablonları ve checklist maddelerini düzenleyebilir.",
        "Bakım kontrol maddeleri, kritik alanlar ve cevap tipleri için şablonları oluşturabilir ve güncelleyebilir.",
    ),
    _permission(
        "workorder.view",
        "İş Emirlerini Görüntüleme",
        "workorder",
        "Açık ve kapanmış iş emirlerini görebilir.",
        "İş emri listesi, detay ekranı, atama bilgisi ve operasyon notlarını görüntüleyebilir.",
    ),
    _permission(
        "workorder.edit",
        "İş Emrini Düzenleme",
        "workorder",
        "İş emri oluşturabilir, atama yapabilir ve detaylarını güncelleyebilir.",
        "Yeni iş emri açabilir, sorumlu atayabilir, öncelik değiştirebilir ve işlem detaylarını düzenleyebilir.",
    ),
    _permission(
        "workorder.approve",
        "İş Emrini Onaylama",
        "workorder",
        "Onay gerektiren iş emri işlemlerini değerlendirebilir.",
        "Kritik iş emri kapanışı veya benzeri approval taleplerini onaylayabilir ya da reddedebilir.",
    ),
    _permission(
        "workorder.close",
        "İş Emrini Kapatma",
        "workorder",
        "Açık iş emirlerini tamamlandı olarak kapatabilir.",
        "Checklist, işçilik ve kullanılan parça bilgileriyle iş emri kapanışını tamamlayabilir.",
    ),
    _permission(
        "parts.view",
        "Parça ve Stokları Görüntüleme",
        "parts",
        "Yedek parça ve stok kayıtlarını görüntüleyebilir.",
        "Parça listesi, düşük stok uyarıları ve stok durum özetlerini görebilir.",
    ),
    _permission(
        "parts.edit",
        "Parça ve Stok Yönetimi",
        "parts",
        "Parça kartları ve stok seviyelerini güncelleyebilir.",
        "Yedek parça giriş/çıkış, stok düzeltme ve kritik stok müdahalelerini yönetebilir.",
    ),
    _permission(
        "users.manage",
        "Kullanıcı Yönetimi",
        "admin",
        "Kullanıcı hesaplarını oluşturabilir, güncelleyebilir ve arşivleyebilir.",
        "Kullanıcı listesi, rol ataması, havalimanı kapsamı ve override izinlerini yönetebilir.",
    ),
    _permission(
        "users.import",
        "Toplu Kullanıcı İçe Aktarma",
        "admin",
        "Excel üzerinden çoklu kullanıcı önizlemesi ve içe aktarma işlemi yapabilir.",
        "Kullanıcı Excel dosyalarını doğrulayıp önizleme sonrası kontrollü olarak sisteme içe aktarabilir.",
    ),
    _permission(
        "users.template.download",
        "Kullanıcı Şablonu İndirme",
        "admin",
        "Örnek kullanıcı Excel şablonunu indirebilir.",
        "Toplu kullanıcı yükleme için örnek Excel şablonunu indirip kurumsal kolon yapısını kullanabilir.",
    ),
    _permission(
        "roles.manage",
        "Rol ve Yetki Yönetimi",
        "admin",
        "Roller, permission matrix ve yetki atamalarını yönetebilir.",
        "Rol kataloğu, permission matrix ve kritik erişim hakları üzerinde değişiklik yapabilir.",
    ),
    _permission(
        "settings.manage",
        "Sistem Ayarlarını Değiştirme",
        "admin",
        "Site ve sistem ayarlarını güncelleyebilir.",
        "Temel sistem davranışlarını, kurumsal ayarları ve yönetim ekranı yapılandırmalarını değiştirebilir.",
    ),
    _permission(
        "logs.view",
        "İşlem Loglarını Görüntüleme",
        "admin",
        "Audit ve işlem loglarını görüntüleyebilir.",
        "Kritik güvenlik olayları, kullanıcı işlemleri ve operasyon kayıtlarını denetleyebilir.",
    ),
    _permission(
        "archive.manage",
        "Arşiv İşlemlerini Yönetme",
        "admin",
        "Arşivlenmiş kayıtları inceleyebilir ve yönetebilir.",
        "Arşive taşınan kayıtları listeleyebilir ve kontrollü geri alma işlemleri yapabilir.",
    ),
    _permission(
        "qr.generate",
        "QR Üretme ve Yazdırma",
        "inventory",
        "Asset ve kutu QR etiketlerini üretebilir ve yazdırabilir.",
        "Standart QR etiketlerini yeniden oluşturabilir, yazdırabilir ve ilgili detay ekranlarına erişebilir.",
    ),
    _permission(
        "reports.view",
        "Rapor ve KPI Ekranlarını Görüntüleme",
        "reports",
        "Rapor merkezi, KPI ekranları ve yönetici özetlerini görebilir.",
        "Operasyonel raporlar, KPI trendleri ve yönetici özet ekranlarına erişebilir.",
    ),
]

DEFAULT_ROLE_PERMISSIONS = {
    ROLE_SYSTEM_OWNER: {item["key"] for item in PERMISSION_DEFINITIONS},
    ROLE_ADMIN: {
        "dashboard.view",
        "homepage.view",
        "homepage.edit",
        "homepage.publish",
        "homepage.media",
        "inventory.view",
        "inventory.create",
        "inventory.edit",
        "inventory.delete",
        "inventory.export",
        "assignment.view",
        "assignment.create",
        "assignment.manage",
        "assignment.pdf",
        "assignment.document.upload",
        "ppe.view",
        "ppe.request",
        "ppe.manage",
        "maintenance.view",
        "maintenance.edit",
        "maintenance.plan.change",
        "maintenance.instructions.manage",
        "maintenance.templates.manage",
        "workorder.view",
        "workorder.edit",
        "workorder.approve",
        "workorder.close",
        "parts.view",
        "parts.edit",
        "users.manage",
        "users.import",
        "users.template.download",
        "roles.manage",
        "logs.view",
        "archive.manage",
        "qr.generate",
        "reports.view",
    },
    ROLE_EDITOR: {
        "dashboard.view",
        "homepage.view",
        "homepage.edit",
        "homepage.publish",
        "homepage.media",
    },
    ROLE_AIRPORT_MANAGER: {
        "dashboard.view",
        "inventory.view",
        "inventory.create",
        "inventory.edit",
        "inventory.export",
        "assignment.view",
        "assignment.create",
        "assignment.manage",
        "assignment.pdf",
        "assignment.document.upload",
        "ppe.view",
        "ppe.request",
        "ppe.manage",
        "maintenance.view",
        "maintenance.edit",
        "maintenance.plan.change",
        "maintenance.instructions.manage",
        "maintenance.templates.manage",
        "workorder.view",
        "workorder.edit",
        "workorder.approve",
        "workorder.close",
        "parts.view",
        "parts.edit",
        "qr.generate",
        "reports.view",
    },
    ROLE_MAINTENANCE: {
        "dashboard.view",
        "inventory.view",
        "assignment.view",
        "maintenance.view",
        "maintenance.edit",
        "maintenance.plan.change",
        "maintenance.instructions.manage",
        "maintenance.templates.manage",
        "workorder.view",
        "workorder.edit",
        "workorder.close",
        "parts.view",
        "ppe.view",
        "ppe.request",
        "qr.generate",
        "reports.view",
    },
    ROLE_WAREHOUSE: {
        "dashboard.view",
        "inventory.view",
        "inventory.create",
        "inventory.edit",
        "inventory.export",
        "assignment.view",
        "assignment.create",
        "assignment.manage",
        "assignment.pdf",
        "assignment.document.upload",
        "ppe.view",
        "ppe.request",
        "ppe.manage",
        "parts.view",
        "parts.edit",
        "qr.generate",
        "reports.view",
    },
    ROLE_PERSONNEL: {
        "dashboard.view",
        "inventory.view",
        "assignment.view",
        "maintenance.view",
        "maintenance.edit",
        "workorder.view",
        "workorder.close",
        "parts.view",
        "ppe.view",
        "ppe.request",
        "qr.generate",
    },
    ROLE_READONLY: {
        "dashboard.view",
        "inventory.view",
        "assignment.view",
        "maintenance.view",
        "workorder.view",
        "parts.view",
        "ppe.view",
        "logs.view",
        "reports.view",
    },
}

MENU_GROUPS = [
    {
        "key": "dashboard",
        "label": "Gösterge Paneli",
        "icon": "KP",
        "single_link": True,
        "items": [
            {
                "label": "Gösterge Paneli",
                "endpoint": "inventory.dashboard",
                "endpoints": ["inventory.dashboard"],
                "permission": "dashboard.view",
            }
        ],
    },
    {
        "key": "content",
        "label": "İçerik Yönetimi",
        "icon": "IC",
        "items": [
            {"label": "Anasayfa Paneli", "endpoint": "content.homepage_dashboard", "endpoints": ["content.homepage_dashboard"], "permission": "homepage.view"},
            {"label": "Slider", "endpoint": "content.homepage_slider_list", "prefixes": ["content.homepage_slider_"], "permission": "homepage.edit"},
            {"label": "Bölümler", "endpoint": "content.homepage_section_list", "prefixes": ["content.homepage_section_"], "permission": "homepage.edit"},
            {"label": "Duyurular", "endpoint": "content.homepage_announcements_list", "prefixes": ["content.homepage_announcement", "content.homepage_announcements_"], "permission": "homepage.edit"},
            {"label": "Formlar / Dokümanlar", "endpoint": "content.homepage_documents_list", "prefixes": ["content.homepage_document", "content.homepage_documents_"], "permission": "homepage.edit"},
            {"label": "Medya", "endpoint": "content.media_library", "prefixes": ["content.media_"], "permission": "homepage.media"},
        ],
    },
    {
        "key": "operations",
        "label": "Operasyon",
        "icon": "OP",
        "items": [
            {"label": "Envanter", "endpoint": "inventory.envanter", "endpoints": ["inventory.envanter", "inventory.malzeme_ekle", "inventory.quick_asset_view", "inventory.kutu_detay"], "permission": "inventory.view"},
            {"label": "Zimmetler", "endpoint": "inventory.zimmetler", "prefixes": ["inventory.zimmet"], "permission": "assignment.view"},
            {"label": "Bakım", "endpoint": "maintenance.bakim_paneli", "prefixes": ["maintenance.bakim_"], "permission": "maintenance.view"},
            {"label": "Bakım Talimatları", "endpoint": "maintenance.ekipman_sablonlari", "prefixes": ["maintenance.ekipman_sablonlari", "maintenance.ekipman_talimat"], "permission": "maintenance.instructions.manage"},
            {"label": "İş Emirleri", "endpoint": "maintenance.is_emirleri", "prefixes": ["maintenance.is_emir", "maintenance.quick_close_work_order"], "permission": "workorder.view"},
            {"label": "KKD Takibi", "endpoint": "inventory.kkd_listesi", "prefixes": ["inventory.kkd"], "permission": "ppe.view"},
            {"label": "Yedek Parçalar", "endpoint": "parts.spare_parts_list", "prefixes": ["parts."], "permission": "parts.view"},
            {"label": "Kutu / Ünite Yönetimi", "endpoint": "inventory.kutular", "endpoints": ["inventory.kutular", "inventory.kutu_detay"], "permission": "inventory.view"},
        ],
    },
    {
        "key": "management",
        "label": "Yönetim",
        "icon": "YN",
        "items": [
            {"label": "Kullanıcılar", "endpoint": "admin.kullanicilar", "endpoints": ["admin.kullanicilar"], "permission": "users.manage"},
            {"label": "Roller / Yetkiler", "endpoint": "admin.roles", "endpoints": ["admin.roles", "admin.permissions"], "prefixes": ["admin.role_detail"], "permission": "roles.manage"},
            {"label": "Site Ayarları", "endpoint": "admin.site_yonetimi", "endpoints": ["admin.site_yonetimi"], "permission": "settings.manage"},
            {"label": "Hata Kayıtları", "endpoint": "admin.hata_kayitlari", "endpoints": ["admin.hata_kayitlari"], "prefixes": ["admin.hata_kaydi_detay"], "permission": "logs.view"},
            {"label": "İşlem Logları", "endpoint": "admin.loglari_gor", "endpoints": ["admin.loglari_gor"], "permission": "logs.view"},
            {"label": "Arşiv", "endpoint": "admin.arsiv_listesi", "endpoints": ["admin.arsiv_listesi"], "permission": "archive.manage"},
        ],
    },
]

LEGACY_ROLE_MAP = {
    ROLE_OWNER: ROLE_OWNER,
    ROLE_MANAGER: ROLE_MANAGER,
    ROLE_HQ: ROLE_HQ,
}


def _normalize_role_key(role):
    role_key = str(role or "").strip()
    return role_key if role_key in ROLE_ALIASES else ""


def _canonical_role(role):
    return ROLE_ALIASES.get(_normalize_role_key(role), "")


def _role_priority(role):
    return ROLE_PRIORITY.get(_canonical_role(role), 0)


def _load_authorization_meta():
    from models import SiteAyarlari

    ayarlar = SiteAyarlari.query.first()
    if not ayarlar or not ayarlar.iletisim_notu:
        return {}
    try:
        data = json.loads(ayarlar.iletisim_notu)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_authorization_meta(meta):
    from extensions import db
    from models import SiteAyarlari

    ayarlar = SiteAyarlari.query.first() or SiteAyarlari()
    if not ayarlar.id:
        db.session.add(ayarlar)
    ayarlar.iletisim_notu = json.dumps(meta, ensure_ascii=False)
    return ayarlar


def get_role_labels():
    labels = DEFAULT_ROLE_LABELS.copy()
    meta = _load_authorization_meta()
    custom = meta.get("role_labels", {})
    if isinstance(custom, dict):
        for role_key in labels:
            value = str(custom.get(role_key, "")).strip()
            if value:
                labels[role_key] = value
    return labels


def get_role_descriptions():
    descriptions = DEFAULT_ROLE_DESCRIPTIONS.copy()
    meta = _load_authorization_meta()
    custom = meta.get("role_descriptions", {})
    if isinstance(custom, dict):
        for role_key in descriptions:
            value = str(custom.get(role_key, "")).strip()
            if value:
                descriptions[role_key] = value
    return descriptions


def get_permission_definitions():
    return list(PERMISSION_DEFINITIONS)


def get_permission_lookup():
    return {item["key"]: item for item in PERMISSION_DEFINITIONS}


def get_permission_module_labels():
    return dict(PERMISSION_MODULE_LABELS)


def get_permission_catalog():
    catalog = {}
    for item in PERMISSION_DEFINITIONS:
        catalog.setdefault(item["module"], []).append(item)
    return catalog


def get_role_options():
    sync_authorization_registry()
    labels = get_role_labels()
    descriptions = get_role_descriptions()
    options = []
    for option in ROLE_OPTIONS:
        copied = dict(option)
        copied["label"] = labels.get(option["key"], option["label"])
        copied["description"] = descriptions.get(option["key"], "")
        options.append(copied)
    return options


def get_role_permissions(role):
    role_key = _normalize_role_key(role)
    canonical = _canonical_role(role_key)
    granted = set(DEFAULT_ROLE_PERMISSIONS.get(canonical, set()))
    if table_exists("role") and table_exists("permission") and table_exists("role_permission"):
        try:
            from models import Permission, Role, RolePermission

            sync_authorization_registry()
            db_role = Role.query.filter(Role.key.in_([role_key, canonical])).order_by(Role.id.asc()).first()
            if db_role:
                assignments = (
                    RolePermission.query.filter_by(role_id=db_role.id)
                    .join(Permission, Permission.id == RolePermission.permission_id)
                    .all()
                )
                for assignment in assignments:
                    if assignment.is_allowed and assignment.permission and assignment.permission.key:
                        granted.add(assignment.permission.key)
                    elif assignment.permission and assignment.permission.key in granted:
                        granted.discard(assignment.permission.key)
        except Exception:
            granted = set(DEFAULT_ROLE_PERMISSIONS.get(canonical, set()))

    meta = _load_authorization_meta()
    matrix = meta.get("permission_matrix", {})
    custom = matrix.get(role_key) or matrix.get(canonical) or {}
    for item in custom.get("allow", []):
        if isinstance(item, str) and item:
            granted.add(item)
    for item in custom.get("deny", []):
        granted.discard(item)
    return granted


def get_user_permission_overrides(user):
    user_id = str(getattr(user, "id", "") or "")
    if not user_id:
        return {"allow": set(), "deny": set()}
    if table_exists("user_permission_override"):
        try:
            from models import UserPermissionOverride

            rows = UserPermissionOverride.query.filter_by(user_id=int(user_id)).all()
            if rows:
                return {
                    "allow": {row.permission_key for row in rows if row.is_allowed},
                    "deny": {row.permission_key for row in rows if not row.is_allowed},
                }
        except Exception:
            pass
    meta = _load_authorization_meta()
    overrides = meta.get("user_permission_overrides", {})
    raw = overrides.get(user_id, {})
    allow = {item for item in raw.get("allow", []) if isinstance(item, str) and item}
    deny = {item for item in raw.get("deny", []) if isinstance(item, str) and item}
    return {"allow": allow, "deny": deny}


def get_effective_permissions(user=None):
    user = user or current_user
    if not getattr(user, "is_authenticated", False):
        return set()
    permissions = set(get_role_permissions(getattr(user, "rol", "")))
    overrides = get_user_permission_overrides(user)
    permissions.update(overrides["allow"])
    permissions.difference_update(overrides["deny"])
    return permissions


def has_permission(permission, user=None):
    return permission in get_effective_permissions(user=user)


def has_any_permission(*permissions, user=None):
    effective = get_effective_permissions(user=user)
    return any(permission in effective for permission in permissions)


def permission_required(*permissions, any_of=False):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(403)
            if any_of:
                if not has_any_permission(*permissions):
                    abort(403)
            else:
                if not all(has_permission(permission) for permission in permissions):
                    abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def _normalize_roles(roles):
    normalized = {_normalize_role_key(role) for role in roles}
    return {role for role in normalized if role}


def _current_role():
    return _normalize_role_key(getattr(current_user, "rol", ""))


def any_role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            izinli_roller = _normalize_roles(roles)
            if not izinli_roller:
                current_app.logger.warning("any_role_required dekoratoru rol verilmeden kullanildi: %s", f.__name__)
                abort(403)
            if not current_user.is_authenticated:
                abort(403)
            if _current_role() not in izinli_roller:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def role_required(role):
    return any_role_required(role)


def rol_gerekli(*roller):
    return any_role_required(*roller)


def homepage_editor_required(f):
    return permission_required("homepage.view")(f)


def has_any_role(*roles):
    if not current_user.is_authenticated:
        return False
    return _current_role() in _normalize_roles(roles)


def has_role(role):
    return has_any_role(role)


def havalimani_filtreli_sorgu(model_sinifi):
    if has_any_permission("settings.manage", "logs.view"):
        return model_sinifi.query
    return model_sinifi.query.filter_by(havalimani_id=current_user.havalimani_id)


def can_assign_role(actor, target_role):
    actor_role = _normalize_role_key(getattr(actor, "rol", ""))
    target_role = _normalize_role_key(target_role)
    if not actor_role or not target_role:
        return False
    if actor_role == ROLE_OWNER:
        return True
    if actor_role == ROLE_ADMIN:
        return target_role not in {ROLE_OWNER, ROLE_ADMIN}
    if actor_role == ROLE_MANAGER:
        return target_role in {ROLE_PERSONNEL, ROLE_MAINTENANCE, ROLE_WAREHOUSE, ROLE_READONLY}
    return False


def actor_can_view_target_user(actor, target_user):
    if not getattr(actor, "is_authenticated", False):
        return False
    if _normalize_role_key(actor.rol) == ROLE_OWNER:
        return True
    if not has_permission("users.manage", user=actor):
        return False
    return getattr(actor, "havalimani_id", None) == getattr(target_user, "havalimani_id", None)


def actor_can_manage_target(actor, target_user):
    if not actor_can_view_target_user(actor, target_user):
        return False
    target_role = _normalize_role_key(getattr(target_user, "rol", ""))
    if not can_assign_role(actor, target_role):
        return False
    return True


def is_editor_only(user=None):
    user = user or current_user
    permissions = get_effective_permissions(user)
    return "homepage.view" in permissions and "inventory.view" not in permissions and "dashboard.view" in permissions


def role_home_endpoint(user=None):
    user = user or current_user
    return "content.homepage_dashboard" if is_editor_only(user) else "inventory.dashboard"


def is_menu_item_active(item, endpoint):
    if not endpoint:
        return False
    if endpoint in item.get("endpoints", []):
        return True
    for prefix in item.get("prefixes", []):
        if endpoint.startswith(prefix):
            return True
    return False


def build_sidebar_groups(user=None):
    user = user or current_user
    if not getattr(user, "is_authenticated", False):
        return []
    endpoint = request.endpoint or ""
    groups = []
    for group in MENU_GROUPS:
        visible_items = []
        for item in group["items"]:
            if not has_permission(item["permission"], user=user):
                continue
            item_copy = dict(item)
            try:
                item_copy["url"] = url_for(item["endpoint"])
            except Exception:
                item_copy["url"] = "#"
            item_copy["active"] = is_menu_item_active(item, endpoint)
            visible_items.append(item_copy)
        if not visible_items:
            continue
        groups.append(
            {
                "key": group["key"],
                "label": group["label"],
                "icon": group["icon"],
                "single_link": group.get("single_link", False),
                "items": visible_items,
                "open": any(item["active"] for item in visible_items),
            }
        )
    return groups


def get_permission_matrix_snapshot():
    rows = []
    catalog = get_permission_definitions()
    options = get_role_options()
    for item in catalog:
        row = {"permission": item, "roles": []}
        for role in options:
            perms = get_role_permissions(role["key"])
            row["roles"].append({"role": role, "granted": item["key"] in perms})
        rows.append(row)
    return rows


def update_permission_matrix(role_key, allow_permissions, deny_permissions):
    meta = _load_authorization_meta()
    matrix = meta.setdefault("permission_matrix", {})
    matrix[role_key] = {
        "allow": sorted({item for item in allow_permissions if item}),
        "deny": sorted({item for item in deny_permissions if item}),
    }
    _save_authorization_meta(meta)
    if table_exists("role") and table_exists("permission") and table_exists("role_permission"):
        try:
            from extensions import db
            from models import Permission, Role, RolePermission

            sync_authorization_registry()
            role = Role.query.filter_by(key=role_key).first()
            if role:
                RolePermission.query.filter_by(role_id=role.id).delete(synchronize_session=False)
                for permission_key in sorted({item for item in allow_permissions if item}):
                    permission = Permission.query.filter_by(key=permission_key).first()
                    if permission:
                        db.session.add(RolePermission(role_id=role.id, permission_id=permission.id, is_allowed=True))
                for permission_key in sorted({item for item in deny_permissions if item}):
                    permission = Permission.query.filter_by(key=permission_key).first()
                    if permission:
                        db.session.add(RolePermission(role_id=role.id, permission_id=permission.id, is_allowed=False))
                db.session.flush()
        except Exception:
            db.session.rollback()
    return meta


def update_user_permission_overrides(user_id, allow_permissions, deny_permissions):
    meta = _load_authorization_meta()
    overrides = meta.setdefault("user_permission_overrides", {})
    overrides[str(user_id)] = {
        "allow": sorted({item for item in allow_permissions if item}),
        "deny": sorted({item for item in deny_permissions if item}),
    }
    _save_authorization_meta(meta)
    if table_exists("user_permission_override"):
        try:
            from extensions import db
            from models import UserPermissionOverride

            UserPermissionOverride.query.filter_by(user_id=int(user_id)).delete(synchronize_session=False)
            for permission_key in sorted({item for item in allow_permissions if item}):
                db.session.add(UserPermissionOverride(user_id=int(user_id), permission_key=permission_key, is_allowed=True))
            for permission_key in sorted({item for item in deny_permissions if item}):
                db.session.add(UserPermissionOverride(user_id=int(user_id), permission_key=permission_key, is_allowed=False))
            db.session.flush()
        except Exception:
            db.session.rollback()
    return meta


def sync_authorization_registry():
    if not (table_exists("role") and table_exists("permission")):
        return None
    try:
        from extensions import db
        from models import Permission, Role

        changed = False
        existing_roles = {item.key: item for item in Role.query.all()}
        for option in ROLE_OPTIONS:
            if option["key"] not in existing_roles:
                changed = True
                db.session.add(
                    Role(
                        key=option["key"],
                        label=option["label"],
                        scope=option["scope"],
                        is_system=True,
                        is_active=True,
                    )
                )

        existing_permissions = {item.key: item for item in Permission.query.all()}
        for definition in PERMISSION_DEFINITIONS:
            record = existing_permissions.get(definition["key"])
            if record:
                if record.label != definition["label"]:
                    record.label = definition["label"]
                    changed = True
                if record.module != definition["module"]:
                    record.module = definition["module"]
                    changed = True
                if record.is_active is not True:
                    record.is_active = True
                    changed = True
            else:
                changed = True
                db.session.add(
                    Permission(
                        key=definition["key"],
                        label=definition["label"],
                        module=definition["module"],
                        is_active=True,
                    )
                )
        if changed:
            db.session.flush()
        return changed
    except Exception:
        return None
