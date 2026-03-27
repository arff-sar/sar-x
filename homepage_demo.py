import json
from datetime import timedelta

from flask import current_app

from extensions import db, table_exists
from models import (
    Announcement,
    ContentWorkflow,
    DemoSeedRecord,
    DocumentResource,
    HomeQuickLink,
    HomeSection,
    HomeSlider,
    HomeStatCard,
    SiteAyarlari,
    get_tr_now,
)


HOMEPAGE_DEMO_SEED_TAG = "homepage_demo"
HOMEPAGE_DEMO_STATE_KEY = "homepage_demo_state"
HOMEPAGE_DEMO_LOGO_KEY = "homepage_demo_logo_url"
HOMEPAGE_DEMO_CONTACT_KEY = "homepage_demo_contact_note"
HOMEPAGE_DEMO_LOGO_URL = "https://dummyimage.com/200x200/0b2946/f59e0b.png&text=ARFF+SAR"
HOMEPAGE_DEMO_CONTACT_NOTE = (
    "Eğitim planları, gönüllü katılımı ve saha hazırlıkları için tim koordinasyonuna "
    "kısa bir mesaj bırakabilirsiniz."
)

MODEL_MAP = {
    "HomeSlider": HomeSlider,
    "HomeSection": HomeSection,
    "Announcement": Announcement,
    "DocumentResource": DocumentResource,
    "HomeQuickLink": HomeQuickLink,
    "HomeStatCard": HomeStatCard,
    "ContentWorkflow": ContentWorkflow,
}

SECTION_PAGE_LABELS = {
    "about": "Biz Kimiz",
    "mission": "Misyon ve Vizyon",
    "vision": "Misyon ve Vizyon",
    "ethics": "Etik Değerler",
    "training": "Eğitimler",
    "exercise": "Tatbikatlar",
    "operation": "Tatbikatlar",
}

DEMO_IMAGE_LIBRARY = {
    "hero_team": "https://images.unsplash.com/photo-1618477462146-050d2767eac4?auto=format&fit=crop&w=1600&q=80",
    "hero_training": "https://images.unsplash.com/photo-1584362917165-526a968579e8?auto=format&fit=crop&w=1600&q=80",
    "hero_coordination": "https://images.unsplash.com/photo-1611691543543-6b62f8fc1d1b?auto=format&fit=crop&w=1600&q=80",
    "announcement_training": "https://images.unsplash.com/photo-1526256262350-7da7584cf5eb?auto=format&fit=crop&w=1400&q=80",
    "announcement_night": "https://images.unsplash.com/photo-1593113598332-cd59a93c6138?auto=format&fit=crop&w=1400&q=80",
    "announcement_equipment": "https://images.unsplash.com/photo-1532635241-17e820acc59f?auto=format&fit=crop&w=1400&q=80",
    "announcement_meeting": "https://images.unsplash.com/photo-1551836022-d5d88e9218df?auto=format&fit=crop&w=1400&q=80",
    "announcement_ethics": "https://images.unsplash.com/photo-1529156069898-49953e39b3ac?auto=format&fit=crop&w=1400&q=80",
    "about_team": "https://images.unsplash.com/photo-1618477461853-cf6ed80faba5?auto=format&fit=crop&w=1400&q=80",
    "training_search": "https://images.unsplash.com/photo-1516910817561-6f39db2a7a48?auto=format&fit=crop&w=1400&q=80",
    "training_ppe": "https://images.unsplash.com/photo-1584515933487-779824d29309?auto=format&fit=crop&w=1400&q=80",
    "training_equipment": "https://images.unsplash.com/photo-1600959907703-125ba1374a12?auto=format&fit=crop&w=1400&q=80",
    "training_command": "https://images.unsplash.com/photo-1516307365426-bea591f05011?auto=format&fit=crop&w=1400&q=80",
    "drill_night": "https://images.unsplash.com/photo-1618477247222-acbdb0e159b3?auto=format&fit=crop&w=1400&q=80",
    "drill_access": "https://images.unsplash.com/photo-1586773860418-d37222d8fce3?auto=format&fit=crop&w=1400&q=80",
    "drill_communication": "https://images.unsplash.com/photo-1516841273335-e39b37888115?auto=format&fit=crop&w=1400&q=80",
    "drill_dispatch": "https://images.unsplash.com/photo-1503428593586-e225b39bddfe?auto=format&fit=crop&w=1400&q=80",
}


def homepage_demo_tools_enabled():
    return bool(current_app.config.get("DEMO_TOOLS_ENABLED", False))


def _guard_homepage_demo_tools():
    if not homepage_demo_tools_enabled():
        raise RuntimeError("Anasayfa demo araçları bu ortamda kapalı.")
    if not table_exists("demo_seed_record"):
        if current_app.config.get("AUTO_CREATE_TABLES", False):
            db.create_all()
        else:
            raise RuntimeError("Demo kayıt tablosu eksik. Önce migration çalıştırın.")


def _load_site_meta(ayarlar):
    if not ayarlar or not ayarlar.iletisim_notu:
        return {}
    try:
        parsed = json.loads(ayarlar.iletisim_notu)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        legacy = str(ayarlar.iletisim_notu).strip()
        return {"site_notu": legacy} if legacy else {}


def _save_site_meta(ayarlar, meta):
    ayarlar.iletisim_notu = json.dumps(meta, ensure_ascii=False)


def _ensure_site_settings():
    ayarlar = SiteAyarlari.query.first()
    if ayarlar:
        return ayarlar
    ayarlar = SiteAyarlari()
    db.session.add(ayarlar)
    db.session.flush()
    return ayarlar


def _register_record(instance, label=None):
    existing = DemoSeedRecord.query.filter_by(
        seed_tag=HOMEPAGE_DEMO_SEED_TAG,
        model_name=instance.__class__.__name__,
        record_id=instance.id,
    ).first()
    if existing:
        return existing
    row = DemoSeedRecord(
        seed_tag=HOMEPAGE_DEMO_SEED_TAG,
        model_name=instance.__class__.__name__,
        record_id=instance.id,
        record_label=label,
    )
    db.session.add(row)
    return row


def _tracked_instances(model_name):
    model = MODEL_MAP.get(model_name)
    if model is None:
        return []
    rows = DemoSeedRecord.query.filter_by(
        seed_tag=HOMEPAGE_DEMO_SEED_TAG,
        model_name=model_name,
    ).order_by(DemoSeedRecord.id.asc()).all()
    instances = []
    for row in rows:
        instance = db.session.get(model, row.record_id)
        if instance is not None:
            instances.append(instance)
    return instances


def _tracked_ids(model_name):
    return {item.id for item in _tracked_instances(model_name)}


def homepage_demo_is_active():
    if not table_exists("demo_seed_record") or not table_exists("site_ayarlari"):
        return False
    if DemoSeedRecord.query.filter_by(seed_tag=HOMEPAGE_DEMO_SEED_TAG).first() is None:
        return False
    ayarlar = SiteAyarlari.query.first()
    meta = _load_site_meta(ayarlar)
    state = meta.get(HOMEPAGE_DEMO_STATE_KEY, {})
    return bool(isinstance(state, dict) and state.get("active"))


def filter_homepage_demo_items(items):
    if not items or not homepage_demo_is_active():
        return items
    model_name = items[0].__class__.__name__
    allowed_ids = _tracked_ids(model_name)
    if not allowed_ids:
        return []
    return [item for item in items if item.id in allowed_ids]


def is_homepage_demo_item(item):
    if item is None or not getattr(item, "id", None):
        return False
    if not table_exists("demo_seed_record"):
        return False
    return DemoSeedRecord.query.filter_by(
        seed_tag=HOMEPAGE_DEMO_SEED_TAG,
        model_name=item.__class__.__name__,
        record_id=item.id,
    ).first() is not None


def _set_demo_meta(active, action, message, summary):
    ayarlar = _ensure_site_settings()
    meta = _load_site_meta(ayarlar)
    meta[HOMEPAGE_DEMO_STATE_KEY] = {
        "active": bool(active),
        "action": action,
        "message": message,
        "updated_at": get_tr_now().strftime("%d.%m.%Y %H:%M"),
        "summary": {
            "sliders": summary.get("sliders", 0),
            "announcements": summary.get("announcements", 0),
            "stats": summary.get("stats", 0),
            "sections": summary.get("sections", 0),
        },
    }
    if active:
        meta.setdefault(HOMEPAGE_DEMO_LOGO_KEY, HOMEPAGE_DEMO_LOGO_URL)
        meta.setdefault(HOMEPAGE_DEMO_CONTACT_KEY, HOMEPAGE_DEMO_CONTACT_NOTE)
    else:
        meta.pop(HOMEPAGE_DEMO_LOGO_KEY, None)
        meta.pop(HOMEPAGE_DEMO_CONTACT_KEY, None)
    _save_site_meta(ayarlar, meta)


def get_homepage_demo_status():
    state = {}
    if table_exists("site_ayarlari"):
        meta = _load_site_meta(SiteAyarlari.query.first())
        state = meta.get(HOMEPAGE_DEMO_STATE_KEY, {}) if isinstance(meta.get(HOMEPAGE_DEMO_STATE_KEY, {}), dict) else {}
        demo_logo_url = str(meta.get(HOMEPAGE_DEMO_LOGO_KEY) or "").strip()
        demo_contact_note = str(meta.get(HOMEPAGE_DEMO_CONTACT_KEY) or "").strip()
    else:
        demo_logo_url = ""
        demo_contact_note = ""

    sliders = _tracked_instances("HomeSlider") if table_exists("demo_seed_record") else []
    announcements = _tracked_instances("Announcement") if table_exists("demo_seed_record") else []
    documents = _tracked_instances("DocumentResource") if table_exists("demo_seed_record") else []
    quick_links = _tracked_instances("HomeQuickLink") if table_exists("demo_seed_record") else []
    stats = _tracked_instances("HomeStatCard") if table_exists("demo_seed_record") else []
    sections = _tracked_instances("HomeSection") if table_exists("demo_seed_record") else []

    page_labels = []
    seen = set()
    for section in sections:
        label = SECTION_PAGE_LABELS.get(section.section_key)
        if label and label not in seen:
            seen.add(label)
            page_labels.append(label)

    training_modules = [item for item in sections if item.section_key == "training"]
    exercise_modules = [item for item in sections if item.section_key in {"exercise", "operation"}]
    installed = bool(sliders or announcements or documents or quick_links or stats or sections)
    active = bool(installed and state.get("active"))

    return {
        "installed": installed,
        "active": active,
        "sliders": len(sliders),
        "announcements": len(announcements),
        "documents": len(documents),
        "quick_links": len(quick_links),
        "stats": len(stats),
        "sections": len(sections),
        "training_modules": len(training_modules),
        "exercise_modules": len(exercise_modules),
        "pages": page_labels,
        "last_action": state.get("action", "idle"),
        "last_message": state.get("message", "Anasayfa demosu henüz kurulmadı."),
        "updated_at": state.get("updated_at", "-"),
        "demo_logo_url": demo_logo_url,
        "demo_contact_note": demo_contact_note,
    }


def format_homepage_demo_summary(summary):
    pages = ", ".join(summary.get("pages", [])) or "-"
    return "\n".join(
        [
            f"Slider: {summary.get('sliders', 0)}",
            f"Duyuru: {summary.get('announcements', 0)}",
            f"Doküman: {summary.get('documents', 0)}",
            f"Hızlı Link: {summary.get('quick_links', 0)}",
            f"Sayısal Özet: {summary.get('stats', 0)}",
            f"İçerik Modülü: {summary.get('sections', 0)}",
            f"Eğitim Modülü: {summary.get('training_modules', 0)}",
            f"Tatbikat Modülü: {summary.get('exercise_modules', 0)}",
            f"Oluşan Sayfalar: {pages}",
        ]
    )


def _published_workflow(entity_type, entity_id):
    now = get_tr_now()
    workflow = ContentWorkflow.query.filter_by(entity_type=entity_type, entity_id=entity_id).first()
    if workflow is None:
        workflow = ContentWorkflow(
            entity_type=entity_type,
            entity_id=entity_id,
            status="published",
            published_at=now,
            published_by_id=None,
            last_edited_by_id=None,
            last_action="homepage_demo_seed",
        )
        db.session.add(workflow)
        db.session.flush()
    else:
        workflow.status = "published"
        workflow.published_at = workflow.published_at or now
        workflow.last_action = "homepage_demo_seed"
    _register_record(workflow, f"{entity_type}:{entity_id}")
    return workflow


def _create_slider(payload):
    slider = HomeSlider(
        title=payload["title"],
        subtitle=payload.get("subtitle"),
        description=payload.get("description"),
        image_url=payload.get("image_url"),
        button_text=payload.get("button_text", "Detayli Bilgi"),
        button_link=payload.get("button_link", "#"),
        order_index=payload.get("order_index", 0),
        is_active=payload.get("is_active", True),
    )
    db.session.add(slider)
    db.session.flush()
    _register_record(slider, slider.title)
    _published_workflow("slider", slider.id)
    return slider


def _create_announcement(payload):
    item = Announcement(
        title=payload["title"],
        slug=payload["slug"],
        summary=payload.get("summary"),
        content=payload.get("content", ""),
        cover_image=payload.get("cover_image"),
        is_published=payload.get("is_published", True),
        published_at=payload.get("published_at"),
        author_id=None,
    )
    db.session.add(item)
    db.session.flush()
    _register_record(item, item.slug)
    _published_workflow("announcement", item.id)
    return item


def _create_stat(payload):
    card = HomeStatCard(
        title=payload["title"],
        value_text=payload["value_text"],
        subtitle=payload.get("subtitle"),
        icon=payload.get("icon"),
        order_index=payload.get("order_index", 0),
        is_active=payload.get("is_active", True),
    )
    db.session.add(card)
    db.session.flush()
    _register_record(card, card.title)
    _published_workflow("stat", card.id)
    return card


def _create_document(payload):
    item = DocumentResource(
        title=payload["title"],
        description=payload.get("description"),
        file_path=payload.get("file_path"),
        category=payload.get("category"),
        order_index=payload.get("order_index", 0),
        is_active=payload.get("is_active", True),
    )
    db.session.add(item)
    db.session.flush()
    _register_record(item, item.title)
    _published_workflow("document", item.id)
    return item


def _create_quick_link(payload):
    item = HomeQuickLink(
        title=payload["title"],
        description=payload.get("description"),
        link_url=payload.get("link_url", "#"),
        icon=payload.get("icon"),
        order_index=payload.get("order_index", 0),
        is_active=payload.get("is_active", True),
    )
    db.session.add(item)
    db.session.flush()
    _register_record(item, item.title)
    _published_workflow("quicklink", item.id)
    return item


def _create_section(payload):
    section = HomeSection(
        section_key=payload["section_key"],
        title=payload["title"],
        subtitle=payload.get("subtitle"),
        content=payload.get("content"),
        icon=payload.get("icon"),
        image_url=payload.get("image_url"),
        order_index=payload.get("order_index", 0),
        is_active=payload.get("is_active", True),
    )
    db.session.add(section)
    db.session.flush()
    _register_record(section, f"{section.section_key}:{section.title}")
    _published_workflow("section", section.id)
    return section


def _slider_payloads():
    return [
        {
            "title": "ARFF Özel Arama Kurtarma Timi",
            "subtitle": "Hazırlık ve ekip uyumu",
            "description": "Hazırlık, disiplin ve ekip uyumu her gün yeniden kurulur. Eğitim, ekipman kontrolü ve ortak hareket kültürüyle sahaya her zaman hazır kalmaya çalışırız.",
            "image_url": DEMO_IMAGE_LIBRARY["hero_team"],
            "button_text": "Timimizi Tanıyın",
            "button_link": "/hakkimizda/biz-kimiz",
            "order_index": 0,
            "is_active": True,
        },
        {
            "title": "Eğitim ve Hazırlık Sürekliliği",
            "subtitle": "Düzenli tekrar ve ortak uygulama",
            "description": "Düzenli tekrar, ortak uygulama ve görev öncesi hazırlık; güvenli ve kontrollü hareket etmenin temelidir.",
            "image_url": DEMO_IMAGE_LIBRARY["hero_training"],
            "button_text": "Eğitimleri İnceleyin",
            "button_link": "/faaliyetlerimiz/egitimler",
            "order_index": 1,
            "is_active": True,
        },
        {
            "title": "Koordinasyon ve Ekip Ruhu",
            "subtitle": "Sakin koordinasyon ve ortak hareket",
            "description": "İhtiyaç anında doğru ekip, doğru ekipman ve sakin koordinasyonla hareket edebilmek için birlikte çalışırız.",
            "image_url": DEMO_IMAGE_LIBRARY["hero_coordination"],
            "button_text": "Faaliyetlerimizi Görün",
            "button_link": "/faaliyetlerimiz/tatbikatlar",
            "order_index": 2,
            "is_active": True,
        },
    ]


def _announcement_payloads():
    now = get_tr_now()
    return [
        {
            "title": "Hafta sonu ortak eğitim buluşması",
            "slug": "demo-hafta-sonu-ortak-egitim-bulusmasi",
            "summary": "Hafta sonu yapılacak ortak eğitim buluşmasında saha düzeni, ekip içi koordinasyon ve güvenli hareket tekrarları birlikte uygulanacaktır.",
            "content": (
                "Buluşma kapsamında ekip görev paylaşımı, kısa saha senaryoları ve temel güvenlik adımları üzerinden "
                "uygulamalı tekrar yapılacak; katılım listesi eğitim öncesi güncellenecektir."
            ),
            "cover_image": DEMO_IMAGE_LIBRARY["announcement_training"],
            "published_at": now - timedelta(days=1, hours=2),
            "is_published": True,
        },
        {
            "title": "Gönüllü koordinasyon toplantısı",
            "slug": "demo-gonullu-koordinasyon-toplantisi",
            "summary": "Gönüllü tim üyeleriyle görev öncesi hazırlık, iletişim akışı ve vardiya koordinasyonunu netleştirmek için toplantı yapılacaktır.",
            "content": (
                "Toplantıda görev dağılımı, iletişim kanalları, sahaya çıkış öncelikleri ve destek ekiplerinin eşleştirilmesi "
                "başlıkları ele alınarak güncel plan duyurulacaktır."
            ),
            "cover_image": DEMO_IMAGE_LIBRARY["announcement_night"],
            "published_at": now - timedelta(days=3, hours=4),
            "is_published": True,
        },
        {
            "title": "Tatbikat hazırlık duyurusu",
            "slug": "demo-tatbikat-hazirlik-duyurusu",
            "summary": "Yaklaşan tatbikat öncesi görev akışı, ekipman dağılımı ve saha güvenlik adımları için son hazırlık paylaşımı yapılmıştır.",
            "content": (
                "Tatbikat gününde görev alacak ekipler, toplanma saatleri, sorumluluk alanları ve emniyet kuralları bu duyuru ile kesinleştirilmiştir."
            ),
            "cover_image": DEMO_IMAGE_LIBRARY["announcement_equipment"],
            "published_at": now - timedelta(days=6, hours=1),
            "is_published": True,
        },
        {
            "title": "Ekipman kontrol haftası",
            "slug": "demo-ekipman-kontrol-haftasi",
            "summary": "Ekipman kontrol haftasında kritik malzeme, kişisel koruyucu donanım ve saha çantası kontrolleri planlı biçimde tamamlanacaktır.",
            "content": (
                "Her birim kendi ekipman listesini güncelleyecek, eksik ve bakım ihtiyacı olan kayıtları sistemde işaretleyerek "
                "hazırlık durumunu görünür hale getirecektir."
            ),
            "cover_image": DEMO_IMAGE_LIBRARY["announcement_meeting"],
            "published_at": now - timedelta(days=9, hours=3),
            "is_published": True,
        },
        {
            "title": "Güvenlik ve etik prensip hatırlatması",
            "slug": "demo-guvenlik-ve-etik-prensip-hatirlatmasi",
            "summary": "Saha görevlerinde güvenli davranış, ekip içi saygı ve etik ilkelere bağlılık için kısa bir hatırlatma paylaşılmıştır.",
            "content": (
                "Tüm görevlerde iletişim disiplini, güvenlik önceliği ve ekip dayanışmasını korumak kritik önem taşır. "
                "Uygulama sırasında etik ilkelere uygun hareket edilmesi beklenmektedir."
            ),
            "cover_image": DEMO_IMAGE_LIBRARY["announcement_ethics"],
            "published_at": now - timedelta(days=12, hours=2),
            "is_published": True,
        },
    ]


def _stat_payloads():
    return [
        {
            "title": "Hazır Ekip",
            "value_text": "0",
            "subtitle": "Görev çağrısına hazır tim personeli.",
            "icon": "●",
            "order_index": 0,
            "is_active": True,
        },
        {
            "title": "Ekipman",
            "value_text": "0",
            "subtitle": "Kontrolü tamamlanan kritik malzeme.",
            "icon": "▲",
            "order_index": 1,
            "is_active": True,
        },
        {
            "title": "Eğitim",
            "value_text": "0",
            "subtitle": "Tamamlanan eğitim ve tekrar oturumu.",
            "icon": "■",
            "order_index": 2,
            "is_active": True,
        },
        {
            "title": "Gönüllü Destek",
            "value_text": "0",
            "subtitle": "Koordinasyona aktif destek veren gönüllü.",
            "icon": "✦",
            "order_index": 3,
            "is_active": True,
        },
    ]


def _section_payloads():
    return [
        {
            "section_key": "about",
            "title": "Biz Kimiz",
            "subtitle": "Ekip Yapısı",
            "content": (
                "ARFF özel arama kurtarma gönüllülerinin birlikte hareket ettiği, hazırlığı canlı tutmayı önemseyen ve sahaya yakın çalışan ekip yapısını temsil ediyoruz. "
                "Eğitim, tekrar, ekipman disiplini ve ortak sorumluluk anlayışıyla görev öncesi hazırlığı sürekli kılmaya odaklanıyoruz."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["about_team"],
            "order_index": 0,
            "is_active": True,
        },
        {
            "section_key": "mission",
            "title": "Misyon",
            "subtitle": "Odak",
            "content": (
                "Hazırlığı canlı tutmak, ekip içi uyumu güçlendirmek, doğru ekipman kullanımını desteklemek ve ihtiyaç anında düzenli, güvenli ve koordineli hareket edebilmek için sürekli gelişen bir çalışma kültürü sürdürmek."
            ),
            "order_index": 1,
            "is_active": True,
        },
        {
            "section_key": "vision",
            "title": "Vizyon",
            "subtitle": "Bakış",
            "content": (
                "Güven, süreklilik, ekip dayanışması ve saha disipliniyle güçlü bir arama kurtarma kültürü oluşturmak; eğitim ve hazırlık sürekliliğini koruyarak örnek bir ekip yapısı ortaya koymak."
            ),
            "order_index": 2,
            "is_active": True,
        },
        {
            "section_key": "ethics",
            "title": "Etik Değerler",
            "subtitle": "İlke",
            "content": (
                "Sorumluluk, saygı, gönüllülük, güven, şeffaflık ve ekip ruhu; tüm hazırlık, eğitim ve saha çalışmalarımızın temelini oluşturur."
            ),
            "order_index": 3,
            "is_active": True,
        },
        {
            "section_key": "training",
            "title": "Temel enkaz arama eğitimi",
            "subtitle": "Eğitim Modülü",
            "content": (
                "Arama düzeni, ekip güvenliği, görev paylaşımı ve temel saha yaklaşımı üzerine uygulamalı başlangıç eğitimi."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["training_search"],
            "order_index": 10,
            "is_active": True,
        },
        {
            "section_key": "training",
            "title": "Kişisel koruyucu donanım eğitimi",
            "subtitle": "Faaliyet Modülü",
            "content": (
                "KKD kullanım sırası, kontrol adımları, doğru ekipman eşleştirmesi ve güvenli çalışma alışkanlığına odaklanan eğitim."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["training_ppe"],
            "order_index": 11,
            "is_active": True,
        },
        {
            "section_key": "training",
            "title": "Ekipman tanıma ve bakım farkındalığı",
            "subtitle": "Eğitim Modülü",
            "content": (
                "Sahada kullanılan ekipmanların temel işlevleri, günlük kontrol noktaları ve bakım sorumluluğuna yönelik farkındalık çalışması."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["training_equipment"],
            "order_index": 12,
            "is_active": True,
        },
        {
            "section_key": "training",
            "title": "Olay yeri koordinasyon eğitimi",
            "subtitle": "Eğitim Modülü",
            "content": (
                "Olay yerinde rol dağılımı, iletişim hiyerarşisi, yönlendirme ve güvenli yaklaşım adımlarını birleştiren koordinasyon eğitimi."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["training_command"],
            "order_index": 13,
            "is_active": True,
        },
        {
            "section_key": "exercise",
            "title": "Gece operasyon hazırlık tatbikatı",
            "subtitle": "Tatbikat Modülü",
            "content": (
                "Gece senaryosunda ekip toplanması, aydınlatma hazırlığı ve görev dağılımı adımlarını içeren uygulama tatbikatı."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["drill_night"],
            "order_index": 20,
            "is_active": True,
        },
        {
            "section_key": "exercise",
            "title": "Kutu ve ünite erişim tatbikatı",
            "subtitle": "Hazırlık Oturumu",
            "content": (
                "Operasyon kutuları ve ünite ekipmanlarına hızlı erişim, dağıtım ve geri toplama adımlarını geliştirmeye yönelik tatbikat."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["drill_access"],
            "order_index": 21,
            "is_active": True,
        },
        {
            "section_key": "exercise",
            "title": "Saha içi iletişim ve görev paylaşımı tatbikatı",
            "subtitle": "Tatbikat Modülü",
            "content": (
                "Kısa saha senaryosunda ekipler arası iletişim, görev devri ve kontrol noktası bildirimlerinin standartlaştırıldığı uygulama."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["drill_communication"],
            "order_index": 22,
            "is_active": True,
        },
        {
            "section_key": "exercise",
            "title": "Toplanma ve sevk koordinasyonu senaryosu",
            "subtitle": "Tatbikat Modülü",
            "content": (
                "Toplanma alanından saha sevkine kadar geçen adımlarda zaman yönetimi, güvenlik teyidi ve koordinasyon akışının test edildiği senaryo."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["drill_dispatch"],
            "order_index": 23,
            "is_active": True,
        },
    ]


def _document_payloads():
    return [
        {
            "title": "ARFF-SAR Operasyon Hazırlık Kontrol Formu",
            "description": "Saha çıkışı öncesi ekipman ve personel kontrol adımlarını içerir.",
            "file_path": "/uploads/demo/arff-sar-operasyon-kontrol-formu.pdf",
            "category": "Operasyon",
            "order_index": 0,
            "is_active": True,
        },
        {
            "title": "Tatbikat Sonrası Değerlendirme Şablonu",
            "description": "Tatbikat gözlemlerini ve iyileştirme maddelerini kaydetmek için örnek şablon.",
            "file_path": "/uploads/demo/tatbikat-sonrasi-degerlendirme.docx",
            "category": "Tatbikat",
            "order_index": 1,
            "is_active": True,
        },
    ]


def _quick_link_payloads():
    return [
        {
            "title": "Eğitim Takvimi",
            "description": "Güncel eğitim planına hızlı erişim",
            "link_url": "/faaliyetlerimiz/egitimler",
            "icon": "calendar",
            "order_index": 0,
            "is_active": True,
        },
        {
            "title": "Tatbikat Arşivi",
            "description": "Önceki tatbikat kayıtlarını görüntüle",
            "link_url": "/faaliyetlerimiz/tatbikatlar",
            "icon": "archive",
            "order_index": 1,
            "is_active": True,
        },
    ]


def seed_homepage_demo_data():
    _guard_homepage_demo_tools()
    existing = DemoSeedRecord.query.filter_by(seed_tag=HOMEPAGE_DEMO_SEED_TAG).first()
    if existing is not None:
        summary = get_homepage_demo_status()
        message = "Anasayfa demo içeriği zaten kurulu. Mevcut demo seti korunuyor."
        _set_demo_meta(True, "already_installed", message, summary)
        db.session.commit()
        return {"created": False, "message": message, "summary": summary}

    for payload in _slider_payloads():
        _create_slider(payload)
    for payload in _announcement_payloads():
        _create_announcement(payload)
    for payload in _document_payloads():
        _create_document(payload)
    for payload in _quick_link_payloads():
        _create_quick_link(payload)
    for payload in _stat_payloads():
        _create_stat(payload)
    for payload in _section_payloads():
        _create_section(payload)

    summary = get_homepage_demo_status()
    message = "Anasayfa demo içeriği kuruldu. Public anasayfa artık yalnızca bu demo setini gösterecek."
    _set_demo_meta(True, "installed", message, summary)
    db.session.commit()
    return {"created": True, "message": message, "summary": get_homepage_demo_status()}


def clear_homepage_demo_data():
    _guard_homepage_demo_tools()
    if not table_exists("demo_seed_record"):
        summary = get_homepage_demo_status()
        return {"deleted": 0, "message": "Anasayfa demo kaydı bulunamadı.", "summary": summary}

    delete_order = [
        "ContentWorkflow",
        "Announcement",
        "DocumentResource",
        "HomeQuickLink",
        "HomeSection",
        "HomeStatCard",
        "HomeSlider",
    ]
    deleted = 0
    for model_name in delete_order:
        model = MODEL_MAP[model_name]
        rows = DemoSeedRecord.query.filter_by(
            seed_tag=HOMEPAGE_DEMO_SEED_TAG,
            model_name=model_name,
        ).order_by(DemoSeedRecord.id.desc()).all()
        for row in rows:
            instance = db.session.get(model, row.record_id)
            if instance is not None:
                db.session.delete(instance)
                deleted += 1

    DemoSeedRecord.query.filter_by(seed_tag=HOMEPAGE_DEMO_SEED_TAG).delete(synchronize_session=False)
    summary = {
        "sliders": 0,
        "announcements": 0,
        "documents": 0,
        "quick_links": 0,
        "stats": 0,
        "sections": 0,
        "training_modules": 0,
        "exercise_modules": 0,
        "pages": [],
    }
    _set_demo_meta(False, "cleared", "Anasayfa demo içeriği temizlendi. Gerçek içerikler tekrar görünür durumda.", summary)
    db.session.commit()
    return {"deleted": deleted, "message": "Anasayfa demo içeriği temizlendi.", "summary": get_homepage_demo_status()}
