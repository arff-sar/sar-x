import json
from functools import wraps

from flask import abort, current_app, g, has_app_context, has_request_context, request, session, url_for
from flask_login import current_user
from sqlalchemy import text

from extensions import column_exists, db, table_exists

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

CANONICAL_ROLE_SYSTEM = "sistem_sorumlusu"
CANONICAL_ROLE_TEAM_LEAD = "ekip_sorumlusu"
CANONICAL_ROLE_TEAM_MEMBER = "ekip_uyesi"
CANONICAL_ROLE_ADMIN = "admin"

CORE_ROLE_KEYS = {
    CANONICAL_ROLE_SYSTEM,
    CANONICAL_ROLE_ADMIN,
    CANONICAL_ROLE_TEAM_LEAD,
    CANONICAL_ROLE_TEAM_MEMBER,
}
ROLE_SWITCH_SESSION_KEY = "temporary_role_override"
REMOVED_ROLE_KEYS = {
    ROLE_OWNER,
    ROLE_SYSTEM_OWNER,
    ROLE_MANAGER,
    ROLE_AIRPORT_MANAGER,
    ROLE_PERSONNEL,
    ROLE_MAINTENANCE,
    ROLE_READONLY,
}

ROLE_ALIASES = {
    CANONICAL_ROLE_SYSTEM: CANONICAL_ROLE_SYSTEM,
    CANONICAL_ROLE_TEAM_LEAD: CANONICAL_ROLE_TEAM_LEAD,
    CANONICAL_ROLE_TEAM_MEMBER: CANONICAL_ROLE_TEAM_MEMBER,
    CANONICAL_ROLE_ADMIN: CANONICAL_ROLE_ADMIN,
    # Legacy/removed role keys are still present in historical records and tests.
    # Map them onto canonical roles so permissions and route guards behave consistently.
    ROLE_OWNER: CANONICAL_ROLE_SYSTEM,
    ROLE_SYSTEM_OWNER: CANONICAL_ROLE_SYSTEM,
    ROLE_MANAGER: CANONICAL_ROLE_TEAM_LEAD,
    ROLE_AIRPORT_MANAGER: CANONICAL_ROLE_TEAM_LEAD,
    ROLE_EDITOR: ROLE_EDITOR,
    ROLE_PERSONNEL: CANONICAL_ROLE_TEAM_MEMBER,
    ROLE_MAINTENANCE: CANONICAL_ROLE_TEAM_MEMBER,
    ROLE_WAREHOUSE: CANONICAL_ROLE_TEAM_MEMBER,
    ROLE_READONLY: CANONICAL_ROLE_ADMIN,
    ROLE_HQ: CANONICAL_ROLE_TEAM_MEMBER,
    ROLE_ADMIN: ROLE_ADMIN,
}

ROLE_PRIORITY = {
    CANONICAL_ROLE_SYSTEM: 100,
    CANONICAL_ROLE_ADMIN: 90,
    CANONICAL_ROLE_TEAM_LEAD: 70,
    CANONICAL_ROLE_TEAM_MEMBER: 40,
}
AIRPORT_SCOPED_ROLE_KEYS = {
    CANONICAL_ROLE_TEAM_LEAD,
    CANONICAL_ROLE_TEAM_MEMBER,
}

DEFAULT_ROLE_LABELS = {
    CANONICAL_ROLE_SYSTEM: "Sistem Sorumlusu",
    CANONICAL_ROLE_ADMIN: "Admin",
    CANONICAL_ROLE_TEAM_LEAD: "Ekip Sorumlusu",
    CANONICAL_ROLE_TEAM_MEMBER: "Ekip Üyesi",
}

DEFAULT_ROLE_DESCRIPTIONS = {
    CANONICAL_ROLE_SYSTEM: "Tüm modüller, tüm havalimanları ve kritik yönetim işlemleri üzerinde tam yetkiye sahiptir.",
    CANONICAL_ROLE_ADMIN: "Tüm havalimanlarını readonly kapsamda izler; kayıtları denetler, ancak değişiklik yapmaz.",
    CANONICAL_ROLE_TEAM_LEAD: "Kendi havalimanında envanter, bakım, zimmet, tatbikat ve operasyonel kullanıcı işlemlerini yönetebilir.",
    CANONICAL_ROLE_TEAM_MEMBER: "Kendi havalimanı kapsamındaki operasyon kayıtlarını görüntüler, bakım doldurur ve kendine ait zimmetleri izler.",
}

ROLE_OPTIONS = [
    {"key": CANONICAL_ROLE_SYSTEM, "label": "Sistem Sorumlusu", "scope": "global", "critical": True, "is_core": True},
    {"key": CANONICAL_ROLE_ADMIN, "label": "Admin", "scope": "global", "critical": False, "is_core": True},
    {"key": CANONICAL_ROLE_TEAM_LEAD, "label": "Ekip Sorumlusu", "scope": "airport", "critical": True, "is_core": True},
    {"key": CANONICAL_ROLE_TEAM_MEMBER, "label": "Ekip Üyesi", "scope": "airport", "critical": False, "is_core": True},
]

LEGACY_ROLE_OPTIONS = [
    {"key": ROLE_EDITOR, "label": "İçerik Editörü", "scope": "global", "critical": False, "is_core": False},
    {"key": ROLE_MAINTENANCE, "label": "Bakım Sorumlusu", "scope": "airport", "critical": False, "is_core": False},
    {"key": ROLE_WAREHOUSE, "label": "Depo Sorumlusu", "scope": "airport", "critical": False, "is_core": False},
    {"key": ROLE_HQ, "label": "Genel Müdürlük", "scope": "global", "critical": False, "is_core": False},
]

PERMISSION_MODULE_LABELS = {
    "dashboard": "Gösterge Paneli",
    "homepage": "İçerik Yönetimi",
    "operations": "Operasyon",
    "inventory": "Envanter",
    "maintenance": "Bakım",
    "workorder": "İş Emirleri",
    "parts": "Parça ve Stok",
    "admin": "Yönetim",
    "reports": "Raporlama",
}


def _rollback_session_safely():
    try:
        db.session.rollback()
    except Exception:
        pass


def _auth_request_cache():
    if not has_request_context():
        return None
    cache = getattr(g, "_auth_runtime_cache", None)
    if cache is None:
        cache = {}
        g._auth_runtime_cache = cache
    return cache


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
        "drill.view",
        "Tatbikat Belgelerini Görüntüleme",
        "operations",
        "Yetki kapsamındaki havalimanına ait tatbikat belgelerini görüntüleyebilir ve indirebilir.",
        "Tatbikat listesi, belge detayı, görüntüleme ve indirme akışlarına yalnız yetki kapsamı içindeki havalimanı için erişebilir.",
    ),
    _permission(
        "drill.manage",
        "Tatbikat Belgelerini Yönetme",
        "operations",
        "Tatbikat belgelerini yükleyebilir ve silebilir.",
        "Google Drive üzerinde tutulan tatbikat dosyalarını yetki kapsamı içindeki havalimanı adına yükleyebilir, ilişkilendirebilir ve silebilir.",
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
        "workorder.create",
        "İş Emri Oluşturma",
        "workorder",
        "Yeni iş emri oluşturabilir.",
        "Asset ve bakım bağlamında yeni iş emri kaydı başlatabilir.",
    ),
    _permission(
        "workorder.edit",
        "İş Emrini Düzenleme",
        "workorder",
        "Mevcut iş emri detaylarını güncelleyebilir.",
        "Mevcut iş emirlerinde durum/öncelik ve işlem detayları gibi alanları düzenleyebilir.",
    ),
    _permission(
        "workorder.assign",
        "İş Emri Atama",
        "workorder",
        "İş emri için sorumlu ataması yapabilir.",
        "İş emrine kullanıcı atama/değiştirme işlemlerini yönetebilir.",
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
    CANONICAL_ROLE_SYSTEM: {item["key"] for item in PERMISSION_DEFINITIONS},
    CANONICAL_ROLE_ADMIN: {
        "dashboard.view",
        "inventory.view",
        "assignment.view",
        "drill.view",
        "maintenance.view",
        "workorder.view",
        "parts.view",
        "ppe.view",
        "reports.view",
        "users.manage",
        "logs.view",
        "qr.generate",
    },
    CANONICAL_ROLE_TEAM_LEAD: {
        "dashboard.view",
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
        "drill.view",
        "drill.manage",
        "ppe.view",
        "ppe.request",
        "ppe.manage",
        "archive.manage",
        "maintenance.view",
        "maintenance.edit",
        "maintenance.plan.change",
        "maintenance.instructions.manage",
        "maintenance.templates.manage",
        "workorder.view",
        "workorder.create",
        "workorder.edit",
        "workorder.assign",
        "workorder.approve",
        "workorder.close",
        "parts.view",
        "parts.edit",
        "users.manage",
        "qr.generate",
        "reports.view",
    },
    CANONICAL_ROLE_TEAM_MEMBER: {
        "dashboard.view",
        "inventory.view",
        "assignment.view",
        "drill.view",
        "maintenance.view",
        "maintenance.edit",
        "workorder.view",
        "workorder.close",
        "parts.view",
        "ppe.view",
        "ppe.request",
        "qr.generate",
        "reports.view",
    },
}

LEGACY_ROLE_DEFAULT_PERMISSIONS = {
    ROLE_OWNER: set(DEFAULT_ROLE_PERMISSIONS[CANONICAL_ROLE_SYSTEM]),
    ROLE_SYSTEM_OWNER: set(DEFAULT_ROLE_PERMISSIONS[CANONICAL_ROLE_SYSTEM]),
    ROLE_EDITOR: {
        "homepage.view",
        "homepage.edit",
        "homepage.media",
    },
    ROLE_PERSONNEL: set(DEFAULT_ROLE_PERMISSIONS[CANONICAL_ROLE_TEAM_MEMBER]),
    ROLE_MAINTENANCE: set(),
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
        "drill.view",
        "ppe.view",
        "ppe.request",
        "ppe.manage",
        "parts.view",
        "parts.edit",
        "qr.generate",
        "reports.view",
    },
    ROLE_HQ: set(DEFAULT_ROLE_PERMISSIONS[CANONICAL_ROLE_TEAM_MEMBER]),
}

for role_key, permissions in LEGACY_ROLE_DEFAULT_PERMISSIONS.items():
    DEFAULT_ROLE_PERMISSIONS.setdefault(role_key, set(permissions))

MENU_GROUPS = [
    {
        "key": "dashboard",
        "label": "Ana Görünüm",
        "icon": "Ana",
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
        "icon": "İç",
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
        "icon": "Saha",
        "items": [
            {"label": "Envanter", "endpoint": "inventory.envanter", "endpoints": ["inventory.envanter", "inventory.malzeme_ekle", "inventory.quick_asset_view", "inventory.asset_detail"], "permission": "inventory.view"},
            {"label": "Zimmetler", "endpoint": "inventory.zimmetler", "prefixes": ["inventory.zimmet"], "permission": "assignment.view"},
            {"label": "Tatbikat", "endpoint": "inventory.tatbikat_listesi", "prefixes": ["inventory.tatbikat_"], "permission": "drill.view"},
            {"label": "Bakım", "endpoint": "maintenance.bakim_paneli", "prefixes": ["maintenance.bakim_"], "permission": "maintenance.view"},
            {"label": "Bakım Talimatları", "endpoint": "maintenance.ekipman_sablonlari", "prefixes": ["maintenance.ekipman_sablonlari", "maintenance.ekipman_talimat"], "permission": "maintenance.instructions.manage"},
            {"label": "İş Emirleri", "endpoint": "maintenance.is_emirleri", "prefixes": ["maintenance.is_emir", "maintenance.quick_close_work_order"], "permission": "workorder.view"},
            {"label": "KKD Takibi", "endpoint": "inventory.kkd_listesi", "prefixes": ["inventory.kkd"], "permission": "ppe.view"},
            {"label": "Kutu Yönetimi", "endpoint": "inventory.kutular", "endpoints": ["inventory.kutular", "inventory.kutu_detay"], "permission": "inventory.view"},
        ],
    },
    {
        "key": "management",
        "label": "Yönetim",
        "icon": "Yön",
        "items": [
            {"label": "Kullanıcılar", "endpoint": "admin.kullanicilar", "endpoints": ["admin.kullanicilar"], "permission": "users.manage"},
            {"label": "Roller / Yetkiler", "endpoint": "admin.roles", "endpoints": ["admin.roles", "admin.permissions"], "prefixes": ["admin.role_detail"], "permission": "roles.manage"},
            {"label": "Site Ayarları", "endpoint": "admin.site_yonetimi", "endpoints": ["admin.site_yonetimi"], "permission": "settings.manage"},
            {"label": "Hata Kayıtları", "endpoint": "admin.hata_kayitlari", "endpoints": ["admin.hata_kayitlari"], "prefixes": ["admin.hata_kaydi_detay"], "permission": "logs.view"},
            {"label": "İşlem Logları", "endpoint": "admin.loglari_gor", "endpoints": ["admin.loglari_gor"], "permission": "logs.view"},
            {"label": "Arşiv", "endpoint": "admin.arsiv_listesi", "endpoints": ["admin.arsiv_listesi"], "permission": "archive.manage"},
            {"label": "Havalimanı Toplu Silme", "endpoint": "admin.site_yonetimi_havalimani_toplu_silme", "endpoints": ["admin.site_yonetimi_havalimani_toplu_silme"], "permission": "settings.manage"},
        ],
    },
]

ROLE_SWITCH_LABELS = {
    CANONICAL_ROLE_SYSTEM: "Sistem Sorumlusu",
    CANONICAL_ROLE_ADMIN: "Admin",
    CANONICAL_ROLE_TEAM_LEAD: "Ekip Sorumlusu",
    CANONICAL_ROLE_TEAM_MEMBER: "Ekip Üyesi",
}


def _normalize_user_identifier(raw_value):
    return str(raw_value or "").strip().lower()


def _role_switch_allow_list():
    configured = ""
    if has_app_context():
        configured = current_app.config.get("ROLE_SWITCH_ALLOWED_USERS", "")
    if isinstance(configured, (list, tuple, set)):
        raw_items = configured
    else:
        raw_items = str(configured or "").split(",")
    normalized = {_normalize_user_identifier(item) for item in raw_items}
    normalized.discard("")
    return normalized


def _role_exists_in_db(role_key):
    if not role_key or not table_exists("role"):
        return False
    try:
        row = db.session.execute(
            text("SELECT 1 FROM role WHERE key = :role_key LIMIT 1"),
            {"role_key": role_key},
        ).first()
        return row is not None
    except Exception:
        _rollback_session_safely()
        return False


def _normalize_role_key(role):
    role_key = str(role or "").strip().lower()
    if not role_key:
        return ""
    if role_key in ROLE_ALIASES:
        return role_key
    return role_key if _role_exists_in_db(role_key) else ""


def _canonical_role(role):
    role_key = _normalize_role_key(role)
    return ROLE_ALIASES.get(role_key, role_key)


def get_legacy_compatible_role(user=None):
    user = user or current_user
    legacy_map = {
        CANONICAL_ROLE_SYSTEM: CANONICAL_ROLE_SYSTEM,
        CANONICAL_ROLE_TEAM_LEAD: CANONICAL_ROLE_TEAM_LEAD,
        CANONICAL_ROLE_TEAM_MEMBER: CANONICAL_ROLE_TEAM_MEMBER,
        CANONICAL_ROLE_ADMIN: CANONICAL_ROLE_ADMIN,
    }
    effective_role = get_effective_role(user)
    return legacy_map.get(effective_role, effective_role)


def expand_role_keys(role):
    canonical = _canonical_role(role)
    if not canonical:
        return set()
    keys = {role_key for role_key, mapped in ROLE_ALIASES.items() if mapped == canonical}
    keys.add(canonical)
    return {item for item in keys if item}


def is_core_role(role):
    return _normalize_role_key(role) in CORE_ROLE_KEYS


def _role_priority(role):
    return ROLE_PRIORITY.get(_canonical_role(role), 0)


def _dynamic_role_switch_options():
    active_core_role_keys = {item["key"] for item in ROLE_OPTIONS}
    options_map = {
        item["key"]: {
            "key": item["key"],
            "label": ROLE_SWITCH_LABELS.get(item["key"], item["label"]),
            "scope": item.get("scope", "global"),
            "is_system": True,
            "is_active": True,
        }
        for item in ROLE_OPTIONS
    }
    legacy_role_keys = {item["key"] for item in LEGACY_ROLE_OPTIONS}
    if table_exists("role") and column_exists("role", "key") and column_exists("role", "label"):
        selected_columns = ["key", "label", "scope"]
        has_is_active = column_exists("role", "is_active")
        has_is_system = column_exists("role", "is_system")
        if has_is_active:
            selected_columns.append("is_active")
        if has_is_system:
            selected_columns.append("is_system")
        try:
            order_clause = "ORDER BY label ASC, key ASC"
            if has_is_system:
                order_clause = "ORDER BY is_system DESC, label ASC, key ASC"
            rows = db.session.execute(
                text(f"SELECT {', '.join(selected_columns)} FROM role {order_clause}")
            ).mappings().all()
            for row in rows:
                role_key = _normalize_role_key(row.get("key"))
                if not role_key or role_key in legacy_role_keys or role_key in REMOVED_ROLE_KEYS:
                    continue
                if bool(row.get("is_system", False)) and role_key not in active_core_role_keys:
                    continue
                if has_is_active and not bool(row.get("is_active", True)):
                    continue
                options_map[role_key] = {
                    "key": role_key,
                    "label": str(row.get("label") or role_key).strip() or role_key,
                    "scope": str(row.get("scope") or "global"),
                    "is_system": bool(row.get("is_system", False)),
                    "is_active": True,
                }
        except Exception:
            _rollback_session_safely()
    return sorted(
        options_map.values(),
        key=lambda item: (-_role_priority(item["key"]), str(item["label"]).lower(), item["key"]),
    )


def _get_role_switch_keys():
    return {item["key"] for item in _dynamic_role_switch_options()}


def can_use_role_switch(user=None):
    user = user or current_user
    if not getattr(user, "is_authenticated", False):
        return False
    identifier = _normalize_user_identifier(getattr(user, "kullanici_adi", ""))
    return identifier in _role_switch_allow_list()


def sanitize_role_override(user=None):
    user = user or current_user
    if not has_request_context():
        return ""
    if not can_use_role_switch(user):
        session.pop(ROLE_SWITCH_SESSION_KEY, None)
        return ""
    current_id = getattr(current_user, "id", None) if getattr(current_user, "is_authenticated", False) else None
    if getattr(user, "id", None) != current_id:
        return ""
    role_key = _normalize_role_key(session.get(ROLE_SWITCH_SESSION_KEY))
    if not role_key:
        session.pop(ROLE_SWITCH_SESSION_KEY, None)
        return ""
    if role_key not in _get_role_switch_keys():
        session.pop(ROLE_SWITCH_SESSION_KEY, None)
        session.modified = True
        return ""
    return role_key


def get_session_role_override(user=None):
    return sanitize_role_override(user)


def get_effective_role(user=None):
    user = user or current_user
    base_role = _normalize_role_key(getattr(user, "rol", ""))
    override = get_session_role_override(user)
    return _canonical_role(override or base_role)


def get_effective_role_label(user=None):
    user = user or current_user
    role_key = get_effective_role(user)
    labels = get_role_labels()
    return ROLE_SWITCH_LABELS.get(role_key) or labels.get(role_key, role_key)


def is_role_switch_active(user=None):
    user = user or current_user
    return bool(get_session_role_override(user))


def is_impersonation_mode(user=None):
    user = user or current_user
    if not getattr(user, "is_authenticated", False):
        return False
    base_role = _canonical_role(getattr(user, "rol", ""))
    override = get_session_role_override(user)
    return bool(override and _canonical_role(override) != base_role)


CONTROL_PLANE_ENDPOINTS = {
    "admin.roles",
    "admin.role_detail",
    "admin.permissions",
    "admin.permissions_export_pdf",
    "admin.role_create",
    "admin.role_update",
    "admin.role_delete",
    "admin.kullanicilar",
    "admin.kullanici_ekle",
    "admin.kullanici_guncelle",
    "admin.kullanici_sil",
    "admin.yetki_isimlerini_guncelle",
    "admin.site_yonetimi",
    "admin.site_ayarlarini_guncelle",
    "admin.approvals",
    "admin.approval_detail",
}

CONTROL_PLANE_PREFIXES = (
    "admin.kullanici_",
    "admin.kullanicilar",
    "admin.role_",
    "admin.permission",
    "admin.approval",
    "admin.havalimani",
    "admin.demo_veri",
    "admin.anasayfa_demo",
    "admin.site_",
    "admin.slider_",
    "admin.menu_",
    "admin.haber_",
)

CONTROL_PLANE_WHITELIST_ENDPOINTS = {
    "auth.role_switch",
    "auth.logout",
}

TEAM_LEAD_IMPERSONATION_ALLOWED_ENDPOINTS = {
    "admin.kullanicilar",
    "admin.kullanici_ekle",
}


def should_block_control_plane(user=None, endpoint=None):
    user = user or current_user
    if not has_request_context():
        return False
    if not is_impersonation_mode(user):
        return False
    resolved_endpoint = str(endpoint or request.endpoint or "").strip()
    if not resolved_endpoint or resolved_endpoint in CONTROL_PLANE_WHITELIST_ENDPOINTS:
        return False
    if get_effective_role(user) == CANONICAL_ROLE_TEAM_LEAD and resolved_endpoint in TEAM_LEAD_IMPERSONATION_ALLOWED_ENDPOINTS:
        return False
    if resolved_endpoint in CONTROL_PLANE_ENDPOINTS:
        return True
    return any(resolved_endpoint.startswith(prefix) for prefix in CONTROL_PLANE_PREFIXES)


def clear_role_override(user=None):
    user = user or current_user
    if has_request_context() and can_use_role_switch(user):
        session.pop(ROLE_SWITCH_SESSION_KEY, None)
        session.modified = True


def set_role_override(role, user=None):
    user = user or current_user
    if not has_request_context() or not can_use_role_switch(user):
        return False, ""
    role_key = _normalize_role_key(role)
    allowed_keys = _get_role_switch_keys()
    if role_key not in allowed_keys:
        return False, ""
    base_role = _normalize_role_key(getattr(user, "rol", ""))
    if _canonical_role(role_key) == _canonical_role(base_role):
        clear_role_override(user)
        return True, _canonical_role(base_role)
    session[ROLE_SWITCH_SESSION_KEY] = role_key
    session.modified = True
    return True, role_key


def get_role_switch_options(user=None):
    user = user or current_user
    if not can_use_role_switch(user):
        return []
    base_role = _canonical_role(getattr(user, "rol", ""))
    active_role = get_effective_role(user)
    labels = get_role_labels()
    options = []
    for item in _dynamic_role_switch_options():
        role_key = item["key"]
        options.append(
            {
                "key": role_key,
                "label": labels.get(role_key, ROLE_SWITCH_LABELS.get(role_key, item["label"])),
                "active": role_key == active_role,
                "base": role_key == base_role,
            }
        )
    return options


def _load_authorization_meta():
    from models import SiteAyarlari

    if not table_exists("site_ayarlari"):
        return {}
    try:
        ayarlar = SiteAyarlari.query.first()
    except Exception:
        _rollback_session_safely()
        return {}
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
    if table_exists("role"):
        try:
            rows = db.session.execute(
                text("SELECT key, label FROM role ORDER BY label ASC, key ASC")
            ).mappings().all()
            for role in rows:
                role_key = str(role.get("key") or "").strip()
                role_label = str(role.get("label") or "").strip()
                if role_key and role_label:
                    labels[role_key] = role_label
        except Exception:
            _rollback_session_safely()
    meta = _load_authorization_meta()
    custom = meta.get("role_labels", {})
    if isinstance(custom, dict):
        for role_key in labels:
            value = str(custom.get(role_key, "")).strip()
            if value:
                labels[role_key] = value
    for role_key, canonical in ROLE_ALIASES.items():
        labels[role_key] = labels.get(canonical, labels.get(role_key, role_key))
    return labels


def get_role_descriptions():
    descriptions = DEFAULT_ROLE_DESCRIPTIONS.copy()
    if table_exists("role") and column_exists("role", "description"):
        try:
            rows = db.session.execute(
                text("SELECT key, description FROM role ORDER BY label ASC, key ASC")
            ).mappings().all()
            for role in rows:
                role_key = str(role.get("key") or "").strip()
                role_description = str(role.get("description") or "").strip()
                if role_key and role_description:
                    descriptions[role_key] = role_description
        except Exception:
            _rollback_session_safely()
    meta = _load_authorization_meta()
    custom = meta.get("role_descriptions", {})
    if isinstance(custom, dict):
        for role_key in descriptions:
            value = str(custom.get(role_key, "")).strip()
            if value:
                descriptions[role_key] = value
    for role_key, canonical in ROLE_ALIASES.items():
        descriptions[role_key] = descriptions.get(canonical, descriptions.get(role_key, ""))
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


def get_manageable_role_options(include_inactive=False):
    sync_authorization_registry()
    options = get_role_options()
    labels = get_role_labels()
    descriptions = get_role_descriptions()
    if not table_exists("role"):
        return options
    if not (column_exists("role", "key") and column_exists("role", "label") and column_exists("role", "is_system")):
        return options
    try:
        selected_columns = ["key", "label", "scope", "is_system"]
        has_is_active = column_exists("role", "is_active")
        has_description = column_exists("role", "description")
        if has_is_active:
            selected_columns.append("is_active")
        if has_description:
            selected_columns.append("description")

        sql = f"SELECT {', '.join(selected_columns)} FROM role WHERE is_system = :is_system"
        params = {"is_system": False}
        if has_is_active and not include_inactive:
            sql += " AND is_active = :is_active"
            params["is_active"] = True
        sql += " ORDER BY label ASC, key ASC"

        for role in db.session.execute(text(sql), params).mappings().all():
            role_key = str(role.get("key") or "").strip()
            if not role_key or role_key in REMOVED_ROLE_KEYS:
                continue
            options.append(
                {
                    "key": role_key,
                    "label": labels.get(role_key, str(role.get("label") or role_key)),
                    "scope": str(role.get("scope") or "global"),
                    "critical": False,
                    "description": descriptions.get(role_key, str(role.get("description") or "").strip()),
                    "is_core": False,
                    "is_system": False,
                    "is_active": bool(role.get("is_active", True)),
                }
            )
    except Exception:
        _rollback_session_safely()
    return options


def get_role_definition(role_key, include_custom=True, allow_legacy=True):
    requested = _normalize_role_key(role_key)
    if not requested:
        return None
    canonical_requested = _canonical_role(requested)
    manageable_options = get_manageable_role_options(include_inactive=allow_legacy)
    for option in manageable_options:
        if option["key"] == requested:
            return option
    if canonical_requested and canonical_requested != requested:
        for option in manageable_options:
            if option["key"] == canonical_requested:
                return option
    if allow_legacy:
        labels = get_role_labels()
        descriptions = get_role_descriptions()
        for option in LEGACY_ROLE_OPTIONS:
            if option["key"] == requested:
                copied = dict(option)
                copied["label"] = labels.get(requested, labels.get(_canonical_role(requested), option["label"]))
                copied["description"] = descriptions.get(requested, descriptions.get(_canonical_role(requested), ""))
                copied["is_active"] = False
                return copied
    if include_custom and _role_exists_in_db(requested):
        labels = get_role_labels()
        descriptions = get_role_descriptions()
        return {
            "key": requested,
            "label": labels.get(requested, requested),
            "scope": "global",
            "critical": False,
            "description": descriptions.get(requested, ""),
            "is_core": False,
            "is_system": False,
            "is_active": True,
        }
    return None


def get_role_permissions(role):
    role_key = _normalize_role_key(role)
    cache = _auth_request_cache()
    cache_key = f"role_permissions:{role_key}"
    if cache is not None and cache_key in cache:
        return set(cache[cache_key])

    canonical = _canonical_role(role_key)
    if role_key in LEGACY_ROLE_DEFAULT_PERMISSIONS:
        granted = set(LEGACY_ROLE_DEFAULT_PERMISSIONS.get(role_key, set()))
    else:
        granted = set(DEFAULT_ROLE_PERMISSIONS.get(canonical, set()))
    if role_key != ROLE_MAINTENANCE and table_exists("role") and table_exists("permission") and table_exists("role_permission"):
        try:
            from models import Permission, RolePermission

            sync_authorization_registry()
            db_role_id = db.session.execute(
                text("SELECT id FROM role WHERE key = :role_key LIMIT 1"),
                {"role_key": role_key},
            ).scalar()
            # Legacy alias roles keep their explicit legacy permission profile.
            # Do not silently inherit canonical DB assignments when alias row is absent.
            if db_role_id is None and canonical != role_key and role_key not in LEGACY_ROLE_DEFAULT_PERMISSIONS:
                db_role_id = db.session.execute(
                    text("SELECT id FROM role WHERE key = :role_key LIMIT 1"),
                    {"role_key": canonical},
                ).scalar()
            if db_role_id:
                assignments = (
                    RolePermission.query.filter_by(role_id=db_role_id)
                    .join(Permission, Permission.id == RolePermission.permission_id)
                    .all()
                )
                for assignment in assignments:
                    if assignment.is_allowed and assignment.permission and assignment.permission.key:
                        granted.add(assignment.permission.key)
                    elif assignment.permission and assignment.permission.key in granted:
                        granted.discard(assignment.permission.key)
        except Exception:
            _rollback_session_safely()
            if role_key in LEGACY_ROLE_DEFAULT_PERMISSIONS:
                granted = set(LEGACY_ROLE_DEFAULT_PERMISSIONS.get(role_key, set()))
            else:
                granted = set(DEFAULT_ROLE_PERMISSIONS.get(canonical, set()))

    meta = _load_authorization_meta()
    matrix = meta.get("permission_matrix", {})
    if role_key == ROLE_MAINTENANCE:
        # Legacy bakım rolü request dışı bağlamda sıfır yetki profilini korur.
        custom = matrix.get(role_key) or {}
    else:
        custom = matrix.get(role_key) or matrix.get(canonical) or {}
    for item in custom.get("allow", []):
        if isinstance(item, str) and item:
            granted.add(item)
    for item in custom.get("deny", []):
        granted.discard(item)
    if cache is not None:
        cache[cache_key] = set(granted)
    return granted


def get_user_permission_overrides(user):
    user_id = str(getattr(user, "id", "") or "")
    cache = _auth_request_cache()
    cache_key = f"user_permission_overrides:{user_id}"
    if cache is not None and cache_key in cache:
        cached = cache[cache_key]
        return {"allow": set(cached["allow"]), "deny": set(cached["deny"])}

    if not user_id:
        return {"allow": set(), "deny": set()}
    if table_exists("user_permission_override"):
        try:
            from models import UserPermissionOverride

            rows = UserPermissionOverride.query.filter_by(user_id=int(user_id)).all()
            if rows:
                result = {
                    "allow": {row.permission_key for row in rows if row.is_allowed},
                    "deny": {row.permission_key for row in rows if not row.is_allowed},
                }
                if cache is not None:
                    cache[cache_key] = {"allow": set(result["allow"]), "deny": set(result["deny"])}
                return result
        except Exception:
            _rollback_session_safely()
    meta = _load_authorization_meta()
    overrides = meta.get("user_permission_overrides", {})
    raw = overrides.get(user_id, {})
    allow = {item for item in raw.get("allow", []) if isinstance(item, str) and item}
    deny = {item for item in raw.get("deny", []) if isinstance(item, str) and item}
    result = {"allow": allow, "deny": deny}
    if cache is not None:
        cache[cache_key] = {"allow": set(result["allow"]), "deny": set(result["deny"])}
    return result


def get_effective_permissions(user=None):
    user = user or current_user
    if not getattr(user, "is_authenticated", False):
        return set()
    override_role = get_session_role_override(user)
    raw_role = _normalize_role_key(getattr(user, "rol", ""))
    cache = _auth_request_cache()
    cache_key = f"effective_permissions:{getattr(user, 'id', '')}:{raw_role}:{override_role or ''}"
    if cache is not None and cache_key in cache:
        return set(cache[cache_key])
    permission_profile_role = override_role or (raw_role if raw_role in LEGACY_ROLE_DEFAULT_PERMISSIONS else get_effective_role(user))
    # Legacy bakım rolü, request bağlamında canonical ekip üyesi davranışıyla çalışmaya devam eder.
    if has_request_context() and not override_role and raw_role == ROLE_MAINTENANCE:
        permission_profile_role = get_effective_role(user)
    permissions = set(get_role_permissions(permission_profile_role))
    overrides = get_user_permission_overrides(user)
    permissions.update(overrides["allow"])
    permissions.difference_update(overrides["deny"])
    if cache is not None:
        cache[cache_key] = set(permissions)
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
    return get_effective_role(current_user)


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
    if get_effective_role(current_user) in AIRPORT_SCOPED_ROLE_KEYS:
        return model_sinifi.query.filter_by(havalimani_id=current_user.havalimani_id)
    if has_any_permission("settings.manage", "logs.view"):
        return model_sinifi.query
    return model_sinifi.query.filter_by(havalimani_id=current_user.havalimani_id)


def can_assign_role(actor, target_role):
    actor_role = get_effective_role(actor)
    target_role = _canonical_role(target_role)
    if not actor_role or not target_role:
        return False
    if actor_role == CANONICAL_ROLE_SYSTEM:
        return True
    if actor_role == CANONICAL_ROLE_TEAM_LEAD:
        return target_role == CANONICAL_ROLE_TEAM_MEMBER
    return False


def actor_can_view_target_user(actor, target_user):
    if not getattr(actor, "is_authenticated", False):
        return False
    actor_role = get_effective_role(actor)
    if actor_role == CANONICAL_ROLE_SYSTEM:
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
    with db.session.no_autoflush:
        meta = _load_authorization_meta()
        matrix = meta.setdefault("permission_matrix", {})
        matrix[role_key] = {
            "allow": sorted({item for item in allow_permissions if item}),
            "deny": sorted({item for item in deny_permissions if item}),
        }
        _save_authorization_meta(meta)
    if table_exists("role") and table_exists("permission") and table_exists("role_permission"):
        try:
            from models import Permission, RolePermission

            sync_authorization_registry()
            savepoint = db.session.begin_nested()
            try:
                role_id = db.session.execute(
                    text("SELECT id FROM role WHERE key = :role_key LIMIT 1"),
                    {"role_key": role_key},
                ).scalar()
                if role_id:
                    RolePermission.query.filter_by(role_id=role_id).delete(synchronize_session=False)
                    for permission_key in sorted({item for item in allow_permissions if item}):
                        permission = Permission.query.filter_by(key=permission_key).first()
                        if permission:
                            db.session.add(
                                RolePermission(role_id=role_id, permission_id=permission.id, is_allowed=True)
                            )
                    for permission_key in sorted({item for item in deny_permissions if item}):
                        permission = Permission.query.filter_by(key=permission_key).first()
                        if permission:
                            db.session.add(
                                RolePermission(role_id=role_id, permission_id=permission.id, is_allowed=False)
                            )
                    db.session.flush()
                savepoint.commit()
            except Exception:
                savepoint.rollback()
                if has_app_context():
                    current_app.logger.exception("Rol izin matrisi veritabanina yansitilamadi: %s", role_key)
        except Exception:
            if has_app_context():
                current_app.logger.exception("Rol izin matrisi guncellenemedi: %s", role_key)
    return meta


def update_user_permission_overrides(user_id, allow_permissions, deny_permissions):
    with db.session.no_autoflush:
        meta = _load_authorization_meta()
        overrides = meta.setdefault("user_permission_overrides", {})
        overrides[str(user_id)] = {
            "allow": sorted({item for item in allow_permissions if item}),
            "deny": sorted({item for item in deny_permissions if item}),
        }
        _save_authorization_meta(meta)
    if table_exists("user_permission_override"):
        try:
            from models import UserPermissionOverride

            savepoint = db.session.begin_nested()
            try:
                UserPermissionOverride.query.filter_by(user_id=int(user_id)).delete(synchronize_session=False)
                for permission_key in sorted({item for item in allow_permissions if item}):
                    db.session.add(
                        UserPermissionOverride(user_id=int(user_id), permission_key=permission_key, is_allowed=True)
                    )
                for permission_key in sorted({item for item in deny_permissions if item}):
                    db.session.add(
                        UserPermissionOverride(user_id=int(user_id), permission_key=permission_key, is_allowed=False)
                    )
                db.session.flush()
                savepoint.commit()
            except Exception:
                savepoint.rollback()
                if has_app_context():
                    current_app.logger.exception(
                        "Kullanici yetki override kaydi veritabanina yansitilamadi: %s", user_id
                    )
        except Exception:
            if has_app_context():
                current_app.logger.exception("Kullanici yetki override guncellenemedi: %s", user_id)
    return meta


def sync_authorization_registry():
    if not (table_exists("role") and table_exists("permission")):
        return None
    required_role_columns = {"key", "label", "scope", "is_system", "is_active", "description"}
    if any(not column_exists("role", column_name) for column_name in required_role_columns):
        return None
    try:
        from extensions import db
        from models import Permission, Role

        changed = False
        existing_roles = {item.key: item for item in Role.query.all()}
        for option in ROLE_OPTIONS:
            record = existing_roles.get(option["key"])
            if record is None:
                changed = True
                db.session.add(
                    Role(
                        key=option["key"],
                        label=option["label"],
                        scope=option["scope"],
                        is_system=True,
                        is_active=True,
                        description=DEFAULT_ROLE_DESCRIPTIONS.get(option["key"], "") if column_exists("role", "description") else None,
                    )
                )
            else:
                if record.label != option["label"]:
                    record.label = option["label"]
                    changed = True
                if record.scope != option["scope"]:
                    record.scope = option["scope"]
                    changed = True
                if record.is_system is not True:
                    record.is_system = True
                    changed = True
                if getattr(record, "is_active", True) is not True:
                    record.is_active = True
                    changed = True
                if column_exists("role", "description"):
                    description = DEFAULT_ROLE_DESCRIPTIONS.get(option["key"], "")
                    if getattr(record, "description", None) != description:
                        record.description = description
                        changed = True

        for option in LEGACY_ROLE_OPTIONS:
            record = existing_roles.get(option["key"])
            if record is None:
                changed = True
                db.session.add(
                    Role(
                        key=option["key"],
                        label=option["label"],
                        scope=option["scope"],
                        is_system=True,
                        is_active=False,
                        description=DEFAULT_ROLE_DESCRIPTIONS.get(_canonical_role(option["key"]), "") if column_exists("role", "description") else None,
                    )
                )
            else:
                if record.label != option["label"]:
                    record.label = option["label"]
                    changed = True
                if record.scope != option["scope"]:
                    record.scope = option["scope"]
                    changed = True
                if record.is_system is not True:
                    record.is_system = True
                    changed = True
                if getattr(record, "is_active", False) is not False:
                    record.is_active = False
                    changed = True
                if column_exists("role", "description"):
                    description = DEFAULT_ROLE_DESCRIPTIONS.get(_canonical_role(option["key"]), "")
                    if getattr(record, "description", None) != description:
                        record.description = description
                        changed = True

        for role_key in REMOVED_ROLE_KEYS:
            record = existing_roles.get(role_key)
            if not record:
                continue
            if getattr(record, "is_active", True):
                record.is_active = False
                changed = True

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
        _rollback_session_safely()
        return None
