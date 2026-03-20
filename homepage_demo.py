import json
from datetime import timedelta

from flask import current_app

from extensions import db, table_exists
from models import (
    Announcement,
    ContentWorkflow,
    DemoSeedRecord,
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
    "hero_team": "https://images.unsplash.com/photo-1517841905240-472988babdf9?auto=format&fit=crop&w=1600&q=80",
    "hero_training": "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=1600&q=80",
    "hero_coordination": "https://images.unsplash.com/photo-1521737604893-d14cc237f11d?auto=format&fit=crop&w=1600&q=80",
    "announcement_training": "https://images.unsplash.com/photo-1517048676732-d65bc937f952?auto=format&fit=crop&w=1400&q=80",
    "announcement_night": "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1400&q=80",
    "announcement_equipment": "https://images.unsplash.com/photo-1516321497487-e288fb19713f?auto=format&fit=crop&w=1400&q=80",
    "announcement_meeting": "https://images.unsplash.com/photo-1529156069898-49953e39b3ac?auto=format&fit=crop&w=1400&q=80",
    "announcement_ethics": "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&w=1400&q=80",
    "about_team": "https://images.unsplash.com/photo-1529156069898-49953e39b3ac?auto=format&fit=crop&w=1400&q=80",
    "training_search": "https://images.unsplash.com/photo-1519389950473-47ba0277781c?auto=format&fit=crop&w=1400&q=80",
    "training_ppe": "https://images.unsplash.com/photo-1520607162513-77705c0f0d4a?auto=format&fit=crop&w=1400&q=80",
    "training_equipment": "https://images.unsplash.com/photo-1516321497487-e288fb19713f?auto=format&fit=crop&w=1400&q=80",
    "training_command": "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?auto=format&fit=crop&w=1400&q=80",
    "drill_night": "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1400&q=80",
    "drill_access": "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?auto=format&fit=crop&w=1400&q=80",
    "drill_communication": "https://images.unsplash.com/photo-1517048676732-d65bc937f952?auto=format&fit=crop&w=1400&q=80",
    "drill_dispatch": "https://images.unsplash.com/photo-1497366754035-f200968a6e72?auto=format&fit=crop&w=1400&q=80",
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
    installed = bool(sliders or announcements or stats or sections)
    active = bool(installed and state.get("active"))

    return {
        "installed": installed,
        "active": active,
        "sliders": len(sliders),
        "announcements": len(announcements),
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
            "title": "Hazırlık sahada değil, her gün birlikte başlar",
            "subtitle": "ARFF Arama Kurtarma Timi",
            "description": "Ekip ruhu, ekipman disiplini ve hazır koordinasyon aynı ritimde tutulur. Sessizce tekrar eden bu hazırlık, sahada sakin ve güvenli hareket etmenin temelini kurar.",
            "image_url": DEMO_IMAGE_LIBRARY["hero_team"],
            "button_text": "Duyurular",
            "button_link": "/duyurular",
            "order_index": 0,
            "is_active": True,
        },
        {
            "title": "Eğitim ve tatbikat aynı refleksi besler",
            "subtitle": "Yakın tekrar, net görev paylaşımı",
            "description": "Her eğitim oturumu görev paylaşımını sadeleştirir; her tatbikat, timin birbirine ne kadar hızlı yaslanabildiğini tekrar gösterir.",
            "image_url": DEMO_IMAGE_LIBRARY["hero_training"],
            "button_text": "Faaliyetlerimiz",
            "button_link": "/faaliyetlerimiz/egitimler",
            "order_index": 1,
            "is_active": True,
        },
        {
            "title": "Sahaya yakın, birbirine güvenen gönüllü yapı",
            "subtitle": "Güven, sorumluluk, dayanışma",
            "description": "Küçük ama uyumlu bir ekip; hızlı toplanma, doğru ekipman seçimi ve sakin koordinasyonla göreve hazır kalır.",
            "image_url": DEMO_IMAGE_LIBRARY["hero_coordination"],
            "button_text": "Biz Kimiz",
            "button_link": "/hakkimizda/biz-kimiz",
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
            "summary": "Temel arama adımları, ekip içi rol dağılımı ve saha giriş hazırlığı için ortak tekrar oturumu planlandı.",
            "content": (
                "Cumartesi sabahı yapılacak ortak oturumda temel enkaz arama akışı, ekip içi rol dağılımı ve ilk saha yaklaşımı adımları üzerinden tekrar geçilecek.\n\n"
                "Çalışma; yeni katılan gönüllülerin ritme dahil olmasını, mevcut ekibin ise aynı dili korumasını hedefliyor. Katılım öncesi kişisel koruyucu donanım kontrolünün tamamlanması ve ekipman teslim kaydının girilmesi bekleniyor.\n\n"
                "Oturum boyunca teorik anlatım yerine kısa tekrarlar, eşli uygulama ve senaryo bazlı koordinasyon tercih edilecek."
            ),
            "cover_image": DEMO_IMAGE_LIBRARY["announcement_training"],
            "published_at": now - timedelta(days=1, hours=2),
            "is_published": True,
        },
        {
            "title": "Gece tatbikatı ön hazırlık paylaşımı",
            "slug": "demo-gece-tatbikati-on-hazirlik-paylasimi",
            "summary": "Aydınlatma, haberleşme ve toplanma akışı gece senaryosu öncesinde tekrar gözden geçirilecek.",
            "content": (
                "Planlanan gece tatbikatı öncesinde ekip liderleriyle kısa bir hazırlık toplantısı yapılacak. Bu paylaşımda aydınlatma ekipmanları, sessiz iletişim kuralları ve sahada görüş sınırı daraldığında uygulanacak rol dağılımı ele alınacak.\n\n"
                "Timden beklenti, toplanma saatine en az on beş dakika önce hazır alanda bulunmak ve kendi ekipman kontrol listesini tamamlamış olmak. Tatbikat boyunca hızdan önce güvenli hareket ve birbirini teyit eden iletişim esas alınacak."
            ),
            "cover_image": DEMO_IMAGE_LIBRARY["announcement_night"],
            "published_at": now - timedelta(days=3, hours=4),
            "is_published": True,
        },
        {
            "title": "Ekipman kontrol haftası başladı",
            "slug": "demo-ekipman-kontrol-haftasi-basladi",
            "summary": "Kullanım yoğunluğu olan ekipmanlar için görünür hasar, şarj ve erişim hızı kontrolleri sıraya alındı.",
            "content": (
                "Bu haftaki odak, sahada ilk ulaşılan ekipmanların sessiz ve düzenli bir akışla kontrol edilmesi. Kesici, aydınlatma, haberleşme ve taşıma ekipmanları için görünür hasar, şarj durumu, etiket okunurluğu ve hızlı erişim adımları gözden geçirilecek.\n\n"
                "Kontrol sırasında eksik veya yorgun parça görülürse yalnızca bildirim bırakmak yerine ilgili sorumluya doğrudan haber verilmesi isteniyor. Amaç kusur aramak değil, timin bir sonraki göreve sakin şekilde hazır olmasını sağlamak."
            ),
            "cover_image": DEMO_IMAGE_LIBRARY["announcement_equipment"],
            "published_at": now - timedelta(days=6, hours=1),
            "is_published": True,
        },
        {
            "title": "Gönüllü koordinasyon toplantısı",
            "slug": "demo-gonullu-koordinasyon-toplantisi",
            "summary": "Yeni dönem görev dağılımı, iletişim zinciri ve saha dışı destek başlıkları kısa bir toplantı ile netleştirilecek.",
            "content": (
                "Aylık koordinasyon buluşmasında yeni döneme ait görev dağılımı, nöbet destek takvimi ve saha dışı lojistik başlıkları birlikte gözden geçirilecek.\n\n"
                "Toplantı resmi bir sunum yerine kısa durum paylaşımları ve ihtiyaç odaklı kararlarla ilerleyecek. Herkesin aynı resmi görmesi, sahaya çıkmadan önce beklenmedik kopuklukları azaltacağı için katılım önemli görülüyor."
            ),
            "cover_image": DEMO_IMAGE_LIBRARY["announcement_meeting"],
            "published_at": now - timedelta(days=9, hours=3),
            "is_published": True,
        },
        {
            "title": "Güvenlik ve etik çizgi hatırlatması",
            "slug": "demo-guvenlik-ve-etik-cizgi-hatirlatmasi",
            "summary": "Her görevde önce insan güvenliği, sonra ekip bütünlüğü ve net sorumluluk zinciri korunacak.",
            "content": (
                "Tüm saha çalışmalarında önce insan güvenliği, sonra ekip bütünlüğü ve son olarak görev verimliliği sırasıyla hareket edilmesi beklenir.\n\n"
                "Kimsenin yalnız bırakılmadığı, teyitsiz bilgiyle hareket edilmediği ve görev dışı görüntü paylaşımında dikkatli davranıldığı çizgi timin güven duygusunu korur. Bu hatırlatma yeni bir kural koymak için değil, mevcut kültürün sesini tazelemek için paylaşıldı."
            ),
            "cover_image": DEMO_IMAGE_LIBRARY["announcement_ethics"],
            "published_at": now - timedelta(days=12, hours=5),
            "is_published": True,
        },
    ]


def _stat_payloads():
    return [
        {
            "title": "Hazır Ekip",
            "value_text": "18 Kişi",
            "subtitle": "Toplanma çağrılarına kısa sürede cevap verebilen aktif tim.",
            "icon": "●",
            "order_index": 0,
            "is_active": True,
        },
        {
            "title": "Ekipman",
            "value_text": "146 Kalem",
            "subtitle": "Sahaya çıkış öncesi kontrol listesine dahil kritik ve destek ekipmanları.",
            "icon": "▲",
            "order_index": 1,
            "is_active": True,
        },
        {
            "title": "Eğitim",
            "value_text": "24 Oturum",
            "subtitle": "Yıllık tekrar takviminde kayıtlı teknik ve koordinasyon çalışmaları.",
            "icon": "■",
            "order_index": 2,
            "is_active": True,
        },
        {
            "title": "Gönüllü Destek",
            "value_text": "32 Görev",
            "subtitle": "Saha dışı hazırlık, lojistik ve bilgi akışını taşıyan gönüllü destek katkısı.",
            "icon": "✦",
            "order_index": 3,
            "is_active": True,
        },
    ]


def _section_payloads():
    return [
        {
            "section_key": "about",
            "title": "Biz Kimiz?",
            "subtitle": "Gönüllü tim yapısı",
            "content": (
                "ARFF Arama Kurtarma Timi; sahaya çıkılması gereken anda birbirini bekletmeden harekete geçebilmek için hazır kalan, görev sırasında sakin iletişimi önceliklendiren ve ekip ruhunu gündelik tekrarlarla büyüten gönüllülerden oluşur.\n\n"
                "Ekibin gücü yalnızca teknik bilgiye değil, birbirinin temposunu tanıyan insanların kurduğu güvene dayanır. Bu yüzden hazırlık bizim için sadece ekipman değil; rol paylaşımı, güvenli davranış ve birbirine destek kültürü anlamına gelir."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["about_team"],
            "order_index": 0,
            "is_active": True,
        },
        {
            "section_key": "mission",
            "title": "Misyon",
            "subtitle": "Hazırlığı canlı tutmak",
            "content": (
                "Misyonumuz; eğitim, tekrar ve sade koordinasyonla timi her zaman göreve yaklaşabilecek bir çizgide tutmak. Hazırlık anlık değil süreklidir; bu nedenle küçük tekrarların ve düzenli iletişim akışının değerini koruruz."
            ),
            "order_index": 1,
            "is_active": True,
        },
        {
            "section_key": "vision",
            "title": "Vizyon",
            "subtitle": "Güven veren saha kültürü",
            "content": (
                "Vizyonumuz; hızlı tepki verirken aceleci davranmayan, farklı deneyim düzeylerini aynı dayanışma çizgisinde buluşturan ve görev anında güven veren bir saha kültürü oluşturmak."
            ),
            "order_index": 2,
            "is_active": True,
        },
        {
            "section_key": "ethics",
            "title": "Etik Değerler",
            "subtitle": "Güven, saygı, sorumluluk",
            "content": (
                "Etik çizgimiz; doğrulanmamış bilgiyle hareket etmemek, her ekip arkadaşına saygı göstermek, görev sırasında görünür olmayan emeği de sahiplenmek ve güvenliği hiçbir hız baskısına feda etmemek üzerine kurulur."
            ),
            "order_index": 3,
            "is_active": True,
        },
        {
            "section_key": "training",
            "title": "Temel enkaz arama eğitimi",
            "subtitle": "Sakin ilerleyen temel tekrar",
            "content": (
                "Arama hattına giriş, güvenli yaklaşım ve ekip içi kısa teyit adımları bu modülde birlikte çalışılır. Amaç, herkesin aynı dili konuşması ve yeni katılan gönüllülerin ritme rahatça dahil olmasıdır."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["training_search"],
            "order_index": 10,
            "is_active": True,
        },
        {
            "section_key": "training",
            "title": "Kişisel koruyucu donanım eğitimi",
            "subtitle": "Güvenlik önce gelir",
            "content": (
                "Kask, gözlük, eldiven ve temel koruyucu setlerin doğru kullanım adımları ekip halinde tekrar edilir. Kişisel hazırlık düzgün olduğunda timin genel hareketi de daha sakin ve hızlı olur."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["training_ppe"],
            "order_index": 11,
            "is_active": True,
        },
        {
            "section_key": "training",
            "title": "Ekipman tanıma ve bakım farkındalığı",
            "subtitle": "Erişim hızı ve doğru kullanım",
            "content": (
                "Sık kullanılan ekipmanların erişim noktası, görünür kontrol adımı ve kullanım öncesi kısa bakım alışkanlığı bu modülü besler. Ekipmanla kurulan sakin ilişki, sahadaki gereksiz gecikmeleri azaltır."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["training_equipment"],
            "order_index": 12,
            "is_active": True,
        },
        {
            "section_key": "training",
            "title": "Olay yeri koordinasyon eğitimi",
            "subtitle": "Rol dağılımı ve iletişim akışı",
            "content": (
                "Toplanma, bilgi aktarımı, görev dağılımı ve geri bildirim halkası bu oturumda bir araya gelir. Ekip içi iletişim netleştikçe sahadaki gerilim azalır, karar hızı ise doğal biçimde artar."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["training_command"],
            "order_index": 13,
            "is_active": True,
        },
        {
            "section_key": "exercise",
            "title": "Gece operasyon hazırlık tatbikatı",
            "subtitle": "Düşük görüşte net koordinasyon",
            "content": (
                "Aydınlatma, sessiz iletişim ve sınırlı görüş koşullarında görev paylaşımı bu tatbikatın odağındadır. Timin birbirini duymadan da tamamlayabilmesi için kısa ve net akışlar tekrarlanır."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["drill_night"],
            "order_index": 20,
            "is_active": True,
        },
        {
            "section_key": "exercise",
            "title": "Kutu ve ünite erişim tatbikatı",
            "subtitle": "Hızlı dağıtım, düzenli hareket",
            "content": (
                "Kutu ve ünite erişiminde doğru sıra, doğru ekipman seçimi ve dağıtım akışı birlikte çalışılır. Amaç sadece hız değil, hızlı kalırken karışıklığa düşmemektir."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["drill_access"],
            "order_index": 21,
            "is_active": True,
        },
        {
            "section_key": "exercise",
            "title": "Saha içi iletişim ve görev paylaşımı tatbikatı",
            "subtitle": "Teyitli bilgi akışı",
            "content": (
                "Kısa raporlama, geri çağrılar ve ekip lideri teyitleri bu senaryoda tekrar edilir. Net bilgi akışının ekip güvenini nasıl koruduğu uygulamalı olarak görülür."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["drill_communication"],
            "order_index": 22,
            "is_active": True,
        },
        {
            "section_key": "exercise",
            "title": "Toplanma ve sevk koordinasyonu senaryosu",
            "subtitle": "Saha öncesi düzen",
            "content": (
                "Toplanma noktasından sevk anına kadar geçen sürede kim neyi taşır, kim kimi teyit eder ve çıkış öncesi son kontrol nasıl yapılır soruları bu senaryoda sade bir akışla denenir."
            ),
            "image_url": DEMO_IMAGE_LIBRARY["drill_dispatch"],
            "order_index": 23,
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
        "stats": 0,
        "sections": 0,
        "training_modules": 0,
        "exercise_modules": 0,
        "pages": [],
    }
    _set_demo_meta(False, "cleared", "Anasayfa demo içeriği temizlendi. Gerçek içerikler tekrar görünür durumda.", summary)
    db.session.commit()
    return {"deleted": deleted, "message": "Anasayfa demo içeriği temizlendi.", "summary": get_homepage_demo_status()}
