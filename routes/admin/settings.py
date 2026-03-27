import json

from flask import current_app, render_template, request, redirect, url_for, flash, abort, session
from flask_login import login_required, current_user

from extensions import db, limiter, log_kaydet, guvenli_metin
from homepage_demo import (
    clear_homepage_demo_data,
    format_homepage_demo_summary,
    get_homepage_demo_status,
    seed_homepage_demo_data,
)
from demo_data import get_platform_demo_status
from models import Havalimani, Haber, Kullanici, NavMenu, SliderResim, SiteAyarlari
from . import admin_bp
from decorators import (
    CANONICAL_ROLE_ADMIN,
    DEFAULT_ROLE_LABELS,
    get_effective_role,
    get_manageable_role_options,
    has_permission,
    get_permission_catalog,
    get_role_permissions,
    get_role_options,
    permission_required,
)


def _load_site_meta(ayarlar):
    """SiteAyarlari.iletisim_notu alanından JSON metadata okur."""
    if not ayarlar or not ayarlar.iletisim_notu:
        return {}

    try:
        data = json.loads(ayarlar.iletisim_notu)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        # Eski düz metin kullanımları bozulmasın diye migrate ediyoruz.
        legacy_note = str(ayarlar.iletisim_notu).strip()
        return {"site_notu": legacy_note} if legacy_note else {}


def _save_site_meta(ayarlar, meta):
    ayarlar.iletisim_notu = json.dumps(meta, ensure_ascii=False)


def _clean_role_label(value, fallback):
    temiz = guvenli_metin(value or "").strip()
    legacy_map = {
        "Havalimani Yoneticisi": "Havalimanı Yöneticisi",
        "Genel Mudurluk": "Genel Müdürlük",
    }
    temiz = legacy_map.get(temiz, temiz)
    return temiz if temiz else fallback


def _resolve_role_labels(ayarlar):
    labels = DEFAULT_ROLE_LABELS.copy()
    meta = _load_site_meta(ayarlar)
    raw_labels = meta.get("role_labels", {})

    if isinstance(raw_labels, dict):
        for role_key in labels:
            labels[role_key] = _clean_role_label(raw_labels.get(role_key), labels[role_key])

    return labels


def _can_manage_demo_mode():
    def _is_demo_manager(user):
        if user is None:
            return False
        if not getattr(user, "is_authenticated", True):
            return False
        return bool(
            getattr(user, "is_sahip", False)
            or get_effective_role(user) == CANONICAL_ROLE_ADMIN
            or has_permission("settings.manage", user=user)
        )

    if current_user.is_authenticated and _is_demo_manager(current_user):
        return True

    # Session üzerinde kullanıcı id varken Flask-Login bağlamı düşerse güvenli fallback.
    try:
        session_user_id = int(str(session.get("_user_id") or "").strip())
    except (TypeError, ValueError):
        return False
    return _is_demo_manager(db.session.get(Kullanici, session_user_id))


# --- HAVALİMANI YÖNETİMİ (SİTE AYARLARI İÇİNE TAŞINDI) ---

@admin_bp.route('/havalimanlari', methods=['GET', 'POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required('settings.manage')
def havalimanlari():
    """Eski endpoint uyumluluğu için korundu, yönetim artık Site Ayarları içinde."""
    if not current_user.is_sahip:
        abort(403)

    if request.method == 'GET':
        return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))

    islem = request.form.get('islem')
    ad = guvenli_metin(request.form.get('ad')).strip()
    kodu = guvenli_metin(request.form.get('kodu')).strip().upper()

    if not ad or not kodu:
        flash("Havalimanı adı ve kodu zorunludur.", "danger")
        return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))

    if islem == 'ekle':
        if Havalimani.query.filter_by(kodu=kodu, is_deleted=False).first():
            flash(f'Hata: {kodu} kodlu bir birim zaten mevcut!', 'danger')
        else:
            yeni_h = Havalimani(ad=ad, kodu=kodu)
            db.session.add(yeni_h)
            db.session.commit()
            log_kaydet('Sistem', f'Yeni birim eklendi: {kodu}')
            flash('Yeni birim başarıyla tanımlandı.', 'success')

    elif islem == 'guncelle':
        h_id = request.form.get('id', type=int)
        h = db.session.get(Havalimani, h_id)
        if not h or h.is_deleted:
            flash("Güncellenecek havalimanı bulunamadı.", "danger")
            return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))

        kod_cakisiyor = Havalimani.query.filter(
            Havalimani.kodu == kodu,
            Havalimani.id != h.id,
            Havalimani.is_deleted.is_(False),
        ).first()
        if kod_cakisiyor:
            flash(f'Hata: {kodu} kodu başka bir birimde kullanılıyor.', 'danger')
            return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))

        eski_ad = h.ad
        eski_kod = h.kodu
        h.ad = ad
        h.kodu = kodu
        db.session.commit()
        log_kaydet('Sistem', f'Birim güncellendi: {eski_kod}/{eski_ad} -> {kodu}/{ad}')
        flash('Birim bilgileri güncellendi.', 'success')

    else:
        flash("Geçersiz havalimanı işlemi.", "danger")

    return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))


@admin_bp.route('/havalimani-sil/<int:id>', methods=['GET'], endpoint='havalimani_sil_legacy')
@login_required
@permission_required('settings.manage')
def havalimani_sil_legacy(id):
    flash("Bu işlem yalnızca form gönderimi ile yapılabilir.", "warning")
    return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))


@admin_bp.route('/havalimani-sil/<int:id>', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required('settings.manage')
def havalimani_sil(id):
    """Birimi fiziksel olarak silmez, arşivler (Soft Delete)."""
    if not current_user.is_sahip:
        abort(403)

    h = db.session.get(Havalimani, id)
    if h and not h.is_deleted:
        kod = h.kodu
        h.soft_delete()
        db.session.commit()
        log_kaydet('Sistem', f'Birim arşivlendi: {kod}')
        flash(f"{kod} birimi arşive taşındı.", "info")
    else:
        flash("Birim bulunamadı.", "danger")

    return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))


@admin_bp.route('/yetki-isimlerini-guncelle', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required('roles.manage')
def yetki_isimlerini_guncelle():
    """Rol isimlerinin görünüm etiketlerini günceller."""
    if not current_user.is_sahip:
        abort(403)

    ayarlar = SiteAyarlari.query.first() or SiteAyarlari()
    if not ayarlar.id:
        db.session.add(ayarlar)

    meta = _load_site_meta(ayarlar)
    mevcut_labels = _resolve_role_labels(ayarlar)

    yeni_labels = {
        "sistem_sorumlusu": _clean_role_label(request.form.get("rol_sistem_sorumlusu"), mevcut_labels["sistem_sorumlusu"]),
        "ekip_sorumlusu": _clean_role_label(request.form.get("rol_ekip_sorumlusu"), mevcut_labels["ekip_sorumlusu"]),
        "ekip_uyesi": _clean_role_label(request.form.get("rol_ekip_uyesi"), mevcut_labels["ekip_uyesi"]),
        "admin": _clean_role_label(request.form.get("rol_admin"), mevcut_labels["admin"]),
    }

    meta["role_labels"] = yeni_labels
    _save_site_meta(ayarlar, meta)
    db.session.commit()

    log_kaydet("Sistem", "Rol etiketleri güncellendi.")
    flash("Yetki isimleri başarıyla güncellendi.", "success")
    return redirect(url_for('admin.site_yonetimi', tab='organizasyon'))


# --- SİTE YÖNETİMİ VE CMS ---

@admin_bp.route('/site-yonetimi')
@login_required
@permission_required('settings.manage')
def site_yonetimi():
    """Site ayarları, organizasyon ve içerik yönetimi."""
    if not _can_manage_demo_mode():
        abort(403)

    ayarlar = SiteAyarlari.query.first()
    meta = _load_site_meta(ayarlar)
    rol_etiketleri = _resolve_role_labels(ayarlar)
    role_catalog = []
    role_usage_counts = {}
    for user in Kullanici.query.filter_by(is_deleted=False).all():
        role_usage_counts[user.rol] = role_usage_counts.get(user.rol, 0) + 1
    for role in get_manageable_role_options():
        role_copy = dict(role)
        role_copy["permission_count"] = len(get_role_permissions(role["key"]))
        role_copy["user_count"] = role_usage_counts.get(role["key"], 0)
        role_catalog.append(role_copy)
    aktif_sekme = request.args.get('tab', 'genel')
    if aktif_sekme not in ['genel', 'organizasyon', 'icerik']:
        aktif_sekme = 'genel'
    platform_demo_status = get_platform_demo_status() if current_app.config.get("DEMO_TOOLS_ENABLED", False) else None
    homepage_demo_status = get_homepage_demo_status() if current_app.config.get("DEMO_TOOLS_ENABLED", False) else None

    return render_template(
        'admin/site_yonetimi.html',
        menuler=NavMenu.query.all(),
        sliderlar=SliderResim.query.all(),
        ayarlar=ayarlar,
        site_notu=meta.get("site_notu", ""),
        public_contact_note=meta.get("public_contact_note", meta.get("site_notu", "")),
        public_logo_url=meta.get("public_logo_url", ""),
        rol_etiketleri=rol_etiketleri,
        role_catalog=role_catalog,
        core_role_keys={item["key"] for item in get_role_options()},
        permission_catalog=get_permission_catalog(),
        havalimanlari=Havalimani.query.filter_by(is_deleted=False).all(),
        aktif_sekme=aktif_sekme,
        demo_tools_enabled=current_app.config.get("DEMO_TOOLS_ENABLED", False),
        platform_demo_status=platform_demo_status,
        homepage_demo_status=homepage_demo_status,
    )


@admin_bp.route('/demo-veri/olustur', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def demo_veri_olustur():
    if not _can_manage_demo_mode():
        abort(403)
    if not current_app.config.get("DEMO_TOOLS_ENABLED", False):
        abort(404)
    if guvenli_metin(request.form.get("confirm_demo_seed")).strip().upper() != "DEMO":
        flash("Demo veri üretimi için onay alanına DEMO yazmalısınız.", "danger")
        return redirect(url_for('admin.site_yonetimi', tab='genel'))

    from demo_data import format_demo_summary, seed_demo_data

    try:
        summary = seed_demo_data(reset=request.form.get("demo_reset") == "1")
    except RuntimeError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for('admin.site_yonetimi', tab='genel'))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Demo veri üretim akışı hata verdi.")
        flash("Demo veri üretimi sırasında bir hata oluştu. İşlem geri alındı.", "danger")
        return redirect(url_for('admin.site_yonetimi', tab='genel'))

    log_kaydet("Demo Veri", f"Demo verisi üretildi.\n{format_demo_summary(summary)}", event_key="demo.seed.create")
    flash("Demo verileri hazırlandı.", "success")
    return redirect(url_for('admin.site_yonetimi', tab='genel'))


@admin_bp.route('/demo-veri/temizle', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def demo_veri_temizle():
    if not _can_manage_demo_mode():
        abort(403)
    if not current_app.config.get("DEMO_TOOLS_ENABLED", False):
        abort(404)
    if guvenli_metin(request.form.get("confirm_demo_clear")).strip().upper() != "DEMO-SIL":
        flash("Demo veri temizliği için onay alanına DEMO-SIL yazmalısınız.", "danger")
        return redirect(url_for('admin.site_yonetimi', tab='genel'))

    from demo_data import clear_demo_data

    try:
        result = clear_demo_data()
    except RuntimeError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for('admin.site_yonetimi', tab='genel'))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Demo veri temizleme akışı hata verdi.")
        flash("Demo veri temizliği sırasında bir hata oluştu. İşlem geri alındı.", "danger")
        return redirect(url_for('admin.site_yonetimi', tab='genel'))

    log_kaydet("Demo Veri", f"Demo verileri temizlendi. Silinen kayıt: {result['deleted']}", event_key="demo.seed.clear")
    flash("Demo verileri temizlendi.", "info")
    return redirect(url_for('admin.site_yonetimi', tab='genel'))


@admin_bp.route('/demo-veri/anasayfa/olustur', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def anasayfa_demo_olustur():
    if not _can_manage_demo_mode():
        abort(403)
    if not current_app.config.get("DEMO_TOOLS_ENABLED", False):
        abort(404)

    try:
        result = seed_homepage_demo_data()
    except RuntimeError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for('admin.site_yonetimi', tab='genel'))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Anasayfa demo üretim akışı hata verdi.")
        flash("Anasayfa demo üretimi sırasında bir hata oluştu. İşlem geri alındı.", "danger")
        return redirect(url_for('admin.site_yonetimi', tab='genel'))

    summary = result["summary"]
    event_key = "demo.homepage.seed.create" if result["created"] else "demo.homepage.seed.skip"
    outcome = "success" if result["created"] else "info"
    log_kaydet(
        "Anasayfa Demo",
        f"{result['message']}\n{format_homepage_demo_summary(summary)}",
        event_key=event_key,
        outcome=outcome,
    )
    flash(result["message"], "success" if result["created"] else "info")
    return redirect(url_for('admin.site_yonetimi', tab='genel'))


@admin_bp.route('/demo-veri/anasayfa/temizle', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
def anasayfa_demo_temizle():
    if not _can_manage_demo_mode():
        abort(403)
    if not current_app.config.get("DEMO_TOOLS_ENABLED", False):
        abort(404)

    try:
        result = clear_homepage_demo_data()
    except RuntimeError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for('admin.site_yonetimi', tab='genel'))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Anasayfa demo temizleme akışı hata verdi.")
        flash("Anasayfa demo temizliği sırasında bir hata oluştu. İşlem geri alındı.", "danger")
        return redirect(url_for('admin.site_yonetimi', tab='genel'))

    event_key = "demo.homepage.seed.clear"
    log_kaydet(
        "Anasayfa Demo",
        f"{result['message']}\nSilinen kayit: {result['deleted']}",
        event_key=event_key,
        outcome="success" if result["deleted"] else "info",
    )
    flash(
        result["message"] if result["deleted"] else "Temizlenecek anasayfa demo kaydi bulunamadi.",
        "info" if result["deleted"] == 0 else "success",
    )
    return redirect(url_for('admin.site_yonetimi', tab='genel'))


@admin_bp.route('/haber-ekle', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required('settings.manage')
def haber_ekle():
    """Site ana sayfasına haber ekler."""
    if not current_user.is_sahip:
        abort(403)

    baslik = guvenli_metin(request.form.get('haber_baslik'))
    icerik = guvenli_metin(request.form.get('haber_icerik'))

    yeni_haber = Haber(baslik=baslik, icerik=icerik)
    db.session.add(yeni_haber)
    db.session.commit()

    log_kaydet("İçerik", f"Yeni haber: {baslik}")
    flash("Haber başarıyla yayınlandı.", "success")
    return redirect(url_for('admin.site_yonetimi', tab='icerik'))


@admin_bp.route('/site-ayarlarini-guncelle', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required('settings.manage')
def site_ayarlarini_guncelle():
    """Global site başlık ve açıklama metinlerini günceller."""
    if not current_user.is_sahip:
        abort(403)

    ayarlar = SiteAyarlari.query.first() or SiteAyarlari()
    if not ayarlar.id:
        db.session.add(ayarlar)

    ayarlar.baslik = guvenli_metin(request.form.get('baslik'))
    ayarlar.alt_metin = guvenli_metin(request.form.get('alt_metin'))

    meta = _load_site_meta(ayarlar)
    logo_url = guvenli_metin(request.form.get("logo_url") or "").strip()
    lowered_logo = logo_url.lower()
    if logo_url and lowered_logo.startswith(("javascript:", "data:", "vbscript:")):
        flash("Logo görsel yolu güvenlik doğrulamasını geçemedi.", "danger")
        return redirect(url_for('admin.site_yonetimi', tab='genel'))

    meta["public_logo_url"] = logo_url
    meta["public_contact_note"] = guvenli_metin(request.form.get("public_contact_note") or request.form.get("iletisim_notu"))
    if "role_labels" not in meta:
        meta["role_labels"] = _resolve_role_labels(ayarlar)
    _save_site_meta(ayarlar, meta)

    db.session.commit()
    log_kaydet("Sistem", "Site ayarları güncellendi.")
    flash("Site ayarları güncellendi.", "success")
    return redirect(url_for('admin.site_yonetimi', tab='genel'))


# --- SLIDER VE MENÜ ---

@admin_bp.route('/slider-ekle', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required('settings.manage')
def slider_ekle():
    if not current_user.is_sahip:
        abort(403)

    yeni = SliderResim(
        resim_url=guvenli_metin(request.form.get('resim_url')),
        baslik=guvenli_metin(request.form.get('slider_baslik'))
    )
    db.session.add(yeni)
    db.session.commit()
    flash("Slider eklendi.", "success")
    return redirect(url_for('admin.site_yonetimi', tab='icerik'))


@admin_bp.route('/slider-guncelle/<int:id>', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required('settings.manage')
def slider_guncelle(id):
    if not current_user.is_sahip:
        abort(403)

    slider = db.session.get(SliderResim, id)
    if not slider:
        flash("Güncellenecek slider bulunamadı.", "danger")
        return redirect(url_for('admin.site_yonetimi', tab='icerik'))

    slider.resim_url = guvenli_metin(request.form.get('resim_url'))
    slider.baslik = guvenli_metin(request.form.get('slider_baslik'))
    db.session.commit()
    flash("Slider güncellendi.", "success")
    return redirect(url_for('admin.site_yonetimi', tab='icerik'))


@admin_bp.route('/slider-sil/<int:id>', methods=['GET'], endpoint='slider_sil_legacy')
@login_required
@permission_required('settings.manage')
def slider_sil_legacy(id):
    flash("Bu işlem yalnızca form gönderimi ile yapılabilir.", "warning")
    return redirect(url_for('admin.site_yonetimi', tab='icerik'))


@admin_bp.route('/slider-sil/<int:id>', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required('settings.manage')
def slider_sil(id):
    if not current_user.is_sahip:
        abort(403)

    slider = db.session.get(SliderResim, id)
    if slider:
        db.session.delete(slider)
        db.session.commit()
        flash("Slider silindi.", "info")
    else:
        flash("Silinecek slider bulunamadı.", "danger")

    return redirect(url_for('admin.site_yonetimi', tab='icerik'))


@admin_bp.route('/menu-ekle', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"))
@permission_required('settings.manage')
def menu_ekle():
    if not current_user.is_sahip:
        abort(403)

    yeni = NavMenu(
        ad=guvenli_metin(request.form.get('menu_ad')),
        link=guvenli_metin(request.form.get('menu_link'))
    )
    db.session.add(yeni)
    db.session.commit()
    flash("Menü eklendi.", "success")
    return redirect(url_for('admin.site_yonetimi', tab='icerik'))


@admin_bp.route('/menu-sil/<int:id>', methods=['GET'], endpoint='menu_sil_legacy')
@login_required
@permission_required('settings.manage')
def menu_sil_legacy(id):
    flash("Bu işlem yalnızca form gönderimi ile yapılabilir.", "warning")
    return redirect(url_for('admin.site_yonetimi', tab='icerik'))


@admin_bp.route('/menu-sil/<int:id>', methods=['POST'])
@login_required
@limiter.limit(lambda: current_app.config.get("CRITICAL_POST_RATE_LIMIT", "20 per minute"), methods=["POST"])
@permission_required('settings.manage')
def menu_sil(id):
    if not current_user.is_sahip:
        abort(403)

    menu = db.session.get(NavMenu, id)
    if menu:
        db.session.delete(menu)
        db.session.commit()
        flash("Menü silindi.", "info")
    else:
        flash("Silinecek menü bulunamadı.", "danger")

    return redirect(url_for('admin.site_yonetimi', tab='icerik'))
