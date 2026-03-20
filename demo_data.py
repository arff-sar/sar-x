import random
from datetime import timedelta

from flask import current_app

from decorators import ROLE_ADMIN, ROLE_AIRPORT_MANAGER, ROLE_EDITOR, ROLE_MAINTENANCE, ROLE_OWNER, ROLE_PERSONNEL, ROLE_READONLY, ROLE_WAREHOUSE
from extensions import db, log_kaydet, table_exists
from models import (
    CalibrationRecord,
    CalibrationSchedule,
    ConsumableItem,
    ConsumableStockMovement,
    DemoSeedRecord,
    EquipmentTemplate,
    Havalimani,
    InventoryAsset,
    Kutu,
    Kullanici,
    MaintenanceFormField,
    MaintenanceFormTemplate,
    MaintenancePlan,
    MaintenanceTriggerRule,
    Malzeme,
    MeterDefinition,
    SparePart,
    SparePartStock,
    Supplier,
    WorkOrder,
    get_tr_now,
)

DEMO_SEED_TAG = "demo_seed"
DEMO_PASSWORD = "Demo.SARx.2026!"
AIRPORTS = [
    ("Erzurum Havalimanı", "ERZ"),
    ("Trabzon Havalimanı", "TZX"),
    ("Kars Havalimanı", "KSY"),
]
ROLE_DISTRIBUTION = [
    ROLE_OWNER,
    ROLE_ADMIN, ROLE_ADMIN,
    ROLE_EDITOR, ROLE_EDITOR, ROLE_EDITOR,
    ROLE_AIRPORT_MANAGER, ROLE_AIRPORT_MANAGER, ROLE_AIRPORT_MANAGER, ROLE_AIRPORT_MANAGER, ROLE_AIRPORT_MANAGER, ROLE_AIRPORT_MANAGER,
    ROLE_MAINTENANCE, ROLE_MAINTENANCE, ROLE_MAINTENANCE, ROLE_MAINTENANCE, ROLE_MAINTENANCE, ROLE_MAINTENANCE,
    ROLE_WAREHOUSE, ROLE_WAREHOUSE, ROLE_WAREHOUSE, ROLE_WAREHOUSE, ROLE_WAREHOUSE, ROLE_WAREHOUSE,
    ROLE_PERSONNEL, ROLE_PERSONNEL, ROLE_PERSONNEL, ROLE_PERSONNEL, ROLE_PERSONNEL, ROLE_PERSONNEL, ROLE_PERSONNEL, ROLE_PERSONNEL, ROLE_PERSONNEL, ROLE_PERSONNEL,
    ROLE_READONLY, ROLE_READONLY, ROLE_READONLY, ROLE_READONLY, ROLE_READONLY, ROLE_READONLY,
]


def demo_tools_enabled():
    return bool(current_app.config.get("DEMO_TOOLS_ENABLED", False))


def _guard_demo_tools():
    if not demo_tools_enabled():
        raise RuntimeError("Demo veri araçları bu ortamda kapalı.")
    if not table_exists("demo_seed_record"):
        if current_app.config.get("AUTO_CREATE_TABLES", False):
            db.create_all()
        else:
            raise RuntimeError("Demo seed tablosu eksik. Önce migration çalıştırın.")


def _register_record(instance, label=None):
    existing = DemoSeedRecord.query.filter_by(
        seed_tag=DEMO_SEED_TAG,
        model_name=instance.__class__.__name__,
        record_id=instance.id,
    ).first()
    if existing:
        return existing
    row = DemoSeedRecord(
        seed_tag=DEMO_SEED_TAG,
        model_name=instance.__class__.__name__,
        record_id=instance.id,
        record_label=label,
    )
    db.session.add(row)
    return row


def _summary():
    return {
        "havalimani": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="Havalimani").count(),
        "kullanici": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="Kullanici").count(),
        "ekipman_sablonu": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="EquipmentTemplate").count(),
        "asset": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="InventoryAsset").count(),
        "kutu": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="Kutu").count(),
        "bakim_formu": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="MaintenanceFormTemplate").count(),
        "bakim_plani": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="MaintenancePlan").count(),
        "is_emri": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="WorkOrder").count(),
        "yedek_parca": DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name="SparePart").count(),
    }


def format_demo_summary(summary):
    return "\n".join(
        [
            f"Havalimanı: {summary['havalimani']}",
            f"Kullanıcı: {summary['kullanici']}",
            f"Ekipman Şablonu: {summary['ekipman_sablonu']}",
            f"Asset: {summary['asset']}",
            f"Kutu/Ünite: {summary['kutu']}",
            f"Bakım Formu: {summary['bakim_formu']}",
            f"Bakım Planı: {summary['bakim_plani']}",
            f"İş Emri: {summary['is_emri']}",
            f"Yedek Parça: {summary['yedek_parca']}",
        ]
    )


def clear_demo_data():
    _guard_demo_tools()
    if not table_exists("demo_seed_record"):
        return {"deleted": 0}

    model_map = {
        "CalibrationRecord": CalibrationRecord,
        "CalibrationSchedule": CalibrationSchedule,
        "ConsumableStockMovement": ConsumableStockMovement,
        "ConsumableItem": ConsumableItem,
        "MaintenanceTriggerRule": MaintenanceTriggerRule,
        "MeterDefinition": MeterDefinition,
        "MaintenancePlan": MaintenancePlan,
        "WorkOrder": WorkOrder,
        "InventoryAsset": InventoryAsset,
        "Malzeme": Malzeme,
        "Kutu": Kutu,
        "SparePartStock": SparePartStock,
        "SparePart": SparePart,
        "Supplier": Supplier,
        "MaintenanceFormField": MaintenanceFormField,
        "MaintenanceFormTemplate": MaintenanceFormTemplate,
        "EquipmentTemplate": EquipmentTemplate,
        "Kullanici": Kullanici,
        "Havalimani": Havalimani,
    }
    delete_order = list(model_map.keys())
    deleted = 0
    for model_name in delete_order:
        rows = DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG, model_name=model_name).order_by(DemoSeedRecord.id.desc()).all()
        model = model_map[model_name]
        for row in rows:
            obj = db.session.get(model, row.record_id)
            if obj is not None:
                db.session.delete(obj)
                deleted += 1
    DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).delete(synchronize_session=False)
    db.session.commit()
    return {"deleted": deleted}


def seed_demo_data(reset=False):
    _guard_demo_tools()
    if reset:
        clear_demo_data()
    elif DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).first():
        return _summary()

    rng = random.Random(20260318)
    today = get_tr_now().date()

    first_names = [
        "Ahmet", "Mehmet", "Ayse", "Fatma", "Mustafa", "Emre", "Burak", "Can", "Seda", "Zeynep",
        "Merve", "Tolga", "Okan", "Sinem", "Berk", "Yasin", "Ece", "Serkan", "Derya", "Gizem",
    ]
    last_names = [
        "Yilmaz", "Demir", "Kaya", "Sahin", "Aydin", "Arslan", "Cetin", "Koc", "Ozdemir", "Kaplan",
        "Aslan", "Kurt", "Polat", "Gunes", "Kilic", "Bulut", "Tas", "Kara", "Avci", "Eren",
    ]
    equipment_specs = [
        ("Hidrolik Kesici", "Kurtarma", 90, "kritik"),
        ("Hidrolik Ayirici", "Kurtarma", 90, "kritik"),
        ("Beton Delici", "Kurtarma", 180, "normal"),
        ("Jenerator", "Enerji", 30, "kritik"),
        ("Gaz Olcum Cihazi", "Olcum", 30, "kritik"),
        ("Termal Kamera", "Gozlem", 90, "kritik"),
        ("Halat Seti", "Kurtarma", 180, "normal"),
        ("Sedye", "Tahliye", 180, "normal"),
        ("El Feneri", "Aydinlatma", 90, "normal"),
        ("Telsiz", "Haberlesme", 180, "kritik"),
        ("Ilk Yardim Cantasi", "Saglik", 180, "normal"),
        ("Koruyucu Kiyafet", "KKD", 180, "normal"),
        ("Solunum Seti", "KKD", 90, "kritik"),
        ("Yangin Sondurucu", "Yangin", 30, "kritik"),
        ("Akulu Projektor", "Aydinlatma", 90, "normal"),
        ("Arama Kamerasi", "Gozlem", 90, "kritik"),
        ("El Aletleri Seti", "Kurtarma", 180, "normal"),
        ("Batarya Sarj Unitesi", "Enerji", 90, "normal"),
        ("Tripod Aydinlatma", "Aydinlatma", 180, "normal"),
        ("Kesme Motoru", "Kurtarma", 90, "kritik"),
        ("Kurtarma Testeresi", "Kurtarma", 90, "kritik"),
        ("Su Tahliye Pompası", "Pompa", 90, "normal"),
        ("Portatif Kompresor", "Enerji", 180, "normal"),
        ("Duman Tahliye Fanı", "Yangin", 90, "kritik"),
        ("Kask Lambasi", "KKD", 180, "normal"),
        ("Kurtarma Yastigi", "Kurtarma", 180, "kritik"),
        ("Bicakli Kurtarma Seti", "Kurtarma", 180, "normal"),
        ("Navigasyon GPS", "Haberlesme", 180, "normal"),
        ("Drone Gozlem Kiti", "Gozlem", 90, "kritik"),
        ("Mobil Isitici", "Destek", 180, "normal"),
    ]
    form_specs = [
        (
            "Jenerator Bakim Formu",
            "Jenerator periyodik kontrol formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("battery_level", "Batarya seviyesi uygun mu", "yes_no"),
                ("cable_check", "Kablo bağlantıları sağlam mı", "yes_no"),
                ("run_test", "Çalıştırma testi geçti mi", "pass_fail"),
                ("oil_level", "Yağ seviyesi", "numeric_reading"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Gaz Olcum Cihazi Kontrol Formu",
            "Gaz olcum ve kalibrasyon checklisti",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("sensor_test", "Sensör testi başarılı mı", "pass_fail"),
                ("calibration_label", "Kalibrasyon etiketi güncel mi", "yes_no"),
                ("battery_level", "Batarya seviyesi uygun mu", "yes_no"),
                ("ppm_reading", "Ölçüm değeri (ppm)", "numeric_reading"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Termal Kamera Kontrol Formu",
            "Lens, batarya ve ekran kontrol listesi",
            [
                ("lens_clean", "Lens temizliği tamam mı", "yes_no"),
                ("screen_check", "Ekran görüntüsü net mi", "pass_fail"),
                ("battery_level", "Batarya seviyesi uygun mu", "yes_no"),
                ("startup_test", "Açılış testi geçti mi", "pass_fail"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Hidrolik Set Kontrol Formu",
            "Kesici ve ayirici operasyon oncesi kontrol formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("hose_integrity", "Kablo / hortum sağlam mı", "yes_no"),
                ("pressure_test", "Basınç testi geçti mi", "pass_fail"),
                ("cleaning_done", "Temizlik yapıldı mı", "yes_no"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Yangin Sondurucu Kontrol Formu",
            "Basinc ve etiket kontrol formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("pressure_ok", "Basınç göstergesi uygun mu", "yes_no"),
                ("label_current", "Kontrol etiketi güncel mi", "yes_no"),
                ("seal_ok", "Mühür ve pim sağlam mı", "pass_fail"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Batarya Saglik Formu",
            "Batarya dongu ve sarj sagligi formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("charge_level", "Şarj seviyesi", "numeric_reading"),
                ("adapter_check", "Şarj adaptörü sağlam mı", "yes_no"),
                ("health_test", "Batarya sağlık testi geçti mi", "pass_fail"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Telsiz Operasyon Formu",
            "Telsiz haberlesme kontrol formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("channel_test", "Kanal testi başarılı mı", "pass_fail"),
                ("audio_quality", "Ses kalitesi yeterli mi", "yes_no"),
                ("battery_level", "Batarya seviyesi uygun mu", "yes_no"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Projektor Kontrol Formu",
            "Projektör ve aydınlatma saha uygunluk formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("light_output", "Işık çıkışı yeterli mi", "pass_fail"),
                ("tripod_check", "Tripod bağlantısı sağlam mı", "yes_no"),
                ("cable_check", "Kablo / fiş sağlam mı", "yes_no"),
                ("notes", "Saha notu", "text"),
            ],
        ),
        (
            "Solunum Seti Kontrol Formu",
            "Solunum seti saha uygunluk formu",
            [
                ("physical_damage", "Fiziksel hasar kontrolü", "checkbox"),
                ("mask_check", "Maske ve bağlantılar sağlam mı", "yes_no"),
                ("pressure_test", "Basınç testi başarılı mı", "pass_fail"),
                ("cleaning_done", "Temizlik yapıldı mı", "yes_no"),
                ("notes", "Saha notu", "text"),
            ],
        ),
    ]
    part_specs = [
        ("BAT-001", "Batarya Paketi", "Enerji"),
        ("HRT-002", "Hortum Seti", "Hidrolik"),
        ("NZL-003", "Nozul", "Yangin"),
        ("FLT-004", "Filtre", "Motor"),
        ("SNS-005", "Sensor Modulu", "Elektronik"),
        ("BCK-006", "Bicak Ucu", "Kesici"),
        ("CHR-007", "Sarj Adaptoru", "Enerji"),
        ("CNT-008", "Conta", "Hidrolik"),
        ("KBL-009", "Kablo Demeti", "Elektrik"),
        ("BAG-010", "Baglanti Aparati", "Montaj"),
        ("LNS-011", "Lens Koruyucu", "Optik"),
        ("FAN-012", "Sogutma Fani", "Motor"),
        ("VAL-013", "Valf", "Hidrolik"),
        ("SIG-014", "Sigorta", "Elektrik"),
        ("BTN-015", "Kontrol Butonu", "Elektronik"),
        ("BTR-016", "Yedek Batarya", "Enerji"),
        ("CHG-017", "Sarj Kablosu", "Enerji"),
        ("MSK-018", "Maske Filtresi", "KKD"),
        ("LCK-019", "Kilitleme Pimi", "Montaj"),
        ("OIL-020", "Bakim Yagi", "Motor"),
    ]
    consumable_specs = [
        ("CON-001", "Eldiven", "KKD", "kutu"),
        ("CON-002", "Maske", "KKD", "adet"),
        ("CON-003", "Pil", "Enerji", "adet"),
        ("CON-004", "Temizlik Malzemesi", "Hijyen", "adet"),
        ("CON-005", "Etiket Kağıdı", "Ofis", "rulo"),
    ]

    airports = []
    for name, code in AIRPORTS:
        airport = Havalimani(ad=name, kodu=code)
        db.session.add(airport)
        db.session.flush()
        _register_record(airport, name)
        airports.append(airport)

    boxes_by_airport = {}
    for airport in airports:
        box_codes = ["KUTU-01", "KUTU-02", "RAF-A1", "RAF-B2", "ARAC-1", "DEPO-01"]
        boxes = []
        for code in box_codes:
            box = Kutu(
                kodu=f"{airport.kodu}-{code}",
                konum=f"{airport.ad} / {code}",
                havalimani_id=airport.id,
            )
            db.session.add(box)
            db.session.flush()
            _register_record(box, box.kodu)
            boxes.append(box)
        boxes_by_airport[airport.id] = boxes

    users = []
    for index, role in enumerate(ROLE_DISTRIBUTION, start=1):
        first_name = first_names[(index - 1) % len(first_names)]
        last_name = last_names[(index * 3) % len(last_names)]
        airport = None if role in {ROLE_OWNER, ROLE_ADMIN, ROLE_EDITOR, ROLE_READONLY} and index % 2 == 0 else airports[(index - 1) % len(airports)]
        username = f"demo.user{index:02d}@sarx.local"
        user = Kullanici(
            kullanici_adi=username,
            tam_ad=f"{first_name} {last_name}",
            rol=role,
            havalimani_id=airport.id if airport else None,
            uzmanlik_alani=rng.choice(["Operasyon", "Bakim", "Lojistik", "Iletisim"]),
        )
        user.sifre_set(DEMO_PASSWORD)
        db.session.add(user)
        db.session.flush()
        _register_record(user, username)
        users.append(user)

    forms = []
    for name, description, field_specs in form_specs:
        form = MaintenanceFormTemplate(name=name, description=description, is_active=True)
        db.session.add(form)
        db.session.flush()
        _register_record(form, name)
        for order_index, (field_key, label, field_type) in enumerate(field_specs, start=1):
            field = MaintenanceFormField(
                form_template_id=form.id,
                field_key=f"{form.id}_{field_key}",
                label=label,
                field_type=field_type,
                is_required=field_key != "notes",
                order_index=order_index,
                options_json=None,
            )
            db.session.add(field)
            db.session.flush()
            _register_record(field, field.field_key)
        forms.append(form)

    def pick_form_for_template(template_name):
        normalized = (template_name or "").lower()
        if "jenerator" in normalized:
            return forms[0]
        if "gaz" in normalized:
            return forms[1]
        if "termal" in normalized or "arama kamerasi" in normalized:
            return forms[2]
        if "hidrolik" in normalized or "kesici" in normalized or "ayirici" in normalized:
            return forms[3]
        if "yangin sondurucu" in normalized:
            return forms[4]
        if "batarya" in normalized:
            return forms[5]
        if "telsiz" in normalized or "gps" in normalized:
            return forms[6]
        if "projektor" in normalized or "aydinlatma" in normalized:
            return forms[7]
        if "solunum" in normalized:
            return forms[8]
        return forms[3]

    templates = []
    for index, (name, category, period_days, criticality) in enumerate(equipment_specs, start=1):
        template = EquipmentTemplate(
            name=name,
            category=category,
            brand=rng.choice(["Holmatro", "Drager", "Flir", "Milwaukee", "Motorola", "Rosenbauer"]),
            model_code=f"MDL-{index:03d}",
            description=f"{name} saha operasyonlari icin demo kaydi",
            technical_specs=f"{category} segmenti icin demo teknik ozellik seti",
            manufacturer=rng.choice(["ARFFTech", "RescuePro", "Opsline"]),
            maintenance_period_days=period_days,
            criticality_level=criticality,
            default_maintenance_form_id=pick_form_for_template(name).id,
            is_active=True,
        )
        db.session.add(template)
        db.session.flush()
        _register_record(template, name)
        templates.append(template)

    suppliers = []
    for supplier_index in range(1, 6):
        supplier = Supplier(
            name=f"Demo Tedarikci {supplier_index}",
            contact_name=f"Tedarik Yetkilisi {supplier_index}",
            phone=f"444 10{supplier_index:02d}",
            email=f"tedarik{supplier_index}@demo.local",
            is_active=True,
        )
        db.session.add(supplier)
        db.session.flush()
        _register_record(supplier, supplier.name)
        suppliers.append(supplier)

    spare_parts = []
    for index, (code, title, category) in enumerate(part_specs, start=1):
        part = SparePart(
            part_code=code,
            title=title,
            category=category,
            manufacturer=rng.choice(["RescuePro", "Opsline", "TechSAR"]),
            model_code=f"PRT-{index:03d}",
            description=f"{title} demo yedek parca kaydi",
            unit="adet",
            min_stock_level=4,
            critical_level=2,
            supplier_id=suppliers[index % len(suppliers)].id,
            is_active=True,
        )
        db.session.add(part)
        db.session.flush()
        _register_record(part, code)
        spare_parts.append(part)
        for airport in airports:
            if index % 5 == 0:
                quantity = 1
            elif index % 3 == 0:
                quantity = 3
            else:
                quantity = rng.randint(7, 18)
            stock = SparePartStock(
                spare_part_id=part.id,
                airport_id=airport.id,
                quantity_on_hand=quantity,
                quantity_reserved=rng.randint(0, 2),
                reorder_point=4,
                shelf_location=f"{airport.kodu}-RAF-{(index % 4) + 1}",
                is_active=True,
            )
            db.session.add(stock)
            db.session.flush()
            _register_record(stock, f"{code}-{airport.kodu}")

    consumables = []
    for code, title, category, unit in consumable_specs:
        item = ConsumableItem(
            code=code,
            title=title,
            category=category,
            unit=unit,
            min_stock_level=5,
            critical_level=2,
            description=f"{title} demo sarf kaydı",
            is_active=True,
        )
        db.session.add(item)
        db.session.flush()
        _register_record(item, code)
        consumables.append(item)
        for airport in airports:
            movement = ConsumableStockMovement(
                consumable_id=item.id,
                airport_id=airport.id,
                movement_type="in",
                quantity=rng.randint(2, 16),
                reference_note="Demo başlangıç stoğu",
                performed_by_id=users[0].id if users else None,
            )
            db.session.add(movement)
            db.session.flush()
            _register_record(movement, f"{code}-{airport.kodu}")

    assets = []
    statuses = ["aktif", "aktif", "aktif", "bakimda", "arizali", "pasif"]
    work_order_statuses = ["acik", "atandi", "islemde", "beklemede_parca", "tamamlandi"]
    work_order_types = ["preventive", "corrective", "inspection", "calibration", "emergency"]
    for airport in airports:
        for asset_index in range(1, 19):
            template = templates[(asset_index + airport.id) % len(templates)]
            box = boxes_by_airport[airport.id][asset_index % len(boxes_by_airport[airport.id])]
            status = statuses[(asset_index + airport.id) % len(statuses)]
            last_maintenance = today - timedelta(days=rng.randint(5, 160))
            next_maintenance = last_maintenance + timedelta(days=template.maintenance_period_days or 90)
            if asset_index % 6 == 0:
                next_maintenance = today - timedelta(days=rng.randint(1, 20))
            elif asset_index % 4 == 0:
                next_maintenance = today + timedelta(days=rng.randint(1, 12))
            material = Malzeme(
                ad=template.name,
                seri_no=f"{airport.kodu}-SN-{asset_index:04d}",
                teknik_ozellikler=template.technical_specs,
                stok_miktari=1,
                durum={"aktif": "Aktif", "bakimda": "Bakımda", "arizali": "Arızalı", "pasif": "Pasif"}[status],
                kritik_mi=template.criticality_level == "kritik",
                son_bakim_tarihi=last_maintenance,
                gelecek_bakim_tarihi=next_maintenance,
                kutu_id=box.id,
                havalimani_id=airport.id,
            )
            db.session.add(material)
            db.session.flush()
            _register_record(material, material.seri_no)

            asset = InventoryAsset(
                equipment_template_id=template.id,
                havalimani_id=airport.id,
                legacy_material_id=material.id,
                serial_no=material.seri_no,
                qr_code="pending",
                asset_tag=f"{airport.kodu}-ASSET-{asset_index:04d}",
                unit_count=1,
                depot_location=box.kodu,
                status=status,
                maintenance_state="gecikmis" if next_maintenance < today else "normal",
                last_maintenance_date=last_maintenance,
                next_maintenance_date=next_maintenance,
                next_calibration_date=today + timedelta(days=rng.randint(-25, 40)),
                acquired_date=today - timedelta(days=rng.randint(180, 720)),
                warranty_end_date=today + timedelta(days=rng.randint(60, 540)),
                notes=f"Demo seed kaydi - {airport.kodu}",
                maintenance_period_days=template.maintenance_period_days,
                is_critical=template.criticality_level == "kritik",
            )
            db.session.add(asset)
            db.session.flush()
            asset.qr_code = f"/demo/asset/{asset.id}"
            _register_record(asset, asset.serial_no)
            assets.append(asset)

            plan = MaintenancePlan(
                name=f"{template.name} Planı",
                equipment_template_id=template.id,
                asset_id=asset.id,
                owner_airport_id=airport.id,
                period_days=rng.choice([30, 90, 180]),
                start_date=today - timedelta(days=rng.randint(30, 180)),
                last_maintenance_date=last_maintenance,
                is_active=True,
                notes="Demo bakım planı",
            )
            plan.recalculate_next_due_date(last_maintenance)
            if asset_index % 6 == 0:
                plan.next_due_date = today - timedelta(days=rng.randint(1, 20))
            elif asset_index % 4 == 0:
                plan.next_due_date = today + timedelta(days=rng.randint(1, 10))
            db.session.add(plan)
            db.session.flush()
            _register_record(plan, plan.name)

            if asset_index % 3 == 0:
                meter = MeterDefinition(
                    name="Çalışma Saati",
                    meter_type="hours",
                    unit="h",
                    asset_id=asset.id,
                    is_active=True,
                )
                db.session.add(meter)
                db.session.flush()
                _register_record(meter, f"meter-{asset.id}")

                rule = MaintenanceTriggerRule(
                    name="Saat Bazli Bakim",
                    trigger_type="hours",
                    asset_id=asset.id,
                    meter_definition_id=meter.id,
                    threshold_value=500,
                    warning_lead_value=25,
                    auto_create_work_order=asset_index % 2 == 0,
                    is_active=True,
                )
                db.session.add(rule)
                db.session.flush()
                _register_record(rule, f"trigger-{asset.id}")

            if template.name in {"Gaz Olcum Cihazi", "Termal Kamera"} or "Gaz" in template.name or "Kamera" in template.name:
                calibration_schedule = CalibrationSchedule(
                    asset_id=asset.id,
                    period_days=180,
                    warning_days=15,
                    provider="Demo Kalibrasyon Servisi",
                    is_active=True,
                    note="Demo kalibrasyon planı",
                )
                db.session.add(calibration_schedule)
                db.session.flush()
                _register_record(calibration_schedule, f"calibration-schedule-{asset.id}")
                calibration_date = today - timedelta(days=rng.randint(20, 140))
                next_calibration_date = calibration_date + timedelta(days=180)
                asset.last_calibration_date = calibration_date
                asset.next_calibration_date = next_calibration_date
                calibration_record = CalibrationRecord(
                    asset_id=asset.id,
                    calibration_schedule_id=calibration_schedule.id,
                    calibration_date=calibration_date,
                    next_calibration_date=next_calibration_date,
                    calibrated_by_id=users[0].id if users else None,
                    provider="Demo Kalibrasyon Servisi",
                    certificate_no=f"CAL-{asset.id:05d}",
                    result_status="passed",
                    note="Demo kalibrasyon kaydı",
                )
                db.session.add(calibration_record)
                db.session.flush()
                _register_record(calibration_record, f"calibration-record-{asset.id}")

    technicians = [user for user in users if user.rol in {ROLE_AIRPORT_MANAGER, ROLE_MAINTENANCE, ROLE_PERSONNEL, ROLE_ADMIN}]
    for index, asset in enumerate(assets[:45], start=1):
        creator = technicians[index % len(technicians)]
        assignee = technicians[(index + 3) % len(technicians)]
        status = work_order_statuses[index % len(work_order_statuses)]
        order = WorkOrder(
            work_order_no=f"WO-DEMO-{index:04d}",
            asset_id=asset.id,
            maintenance_type="bakim" if index % 2 else "ariza",
            work_order_type=work_order_types[index % len(work_order_types)],
            source_type="meter_trigger" if index % 4 == 0 else "manual",
            description=f"{asset.equipment_template.name if asset.equipment_template else 'Asset'} için demo iş emri",
            target_date=today + timedelta(days=rng.randint(-5, 20)),
            assigned_user_id=assignee.id,
            created_user_id=creator.id,
            status=status,
            priority=rng.choice(["dusuk", "orta", "yuksek", "kritik"]),
            completed_at=get_tr_now() if status == "tamamlandi" else None,
            verification_status="beklemede" if status != "tamamlandi" else "dogrulandi",
            checklist_template_id=(asset.equipment_template.default_maintenance_form_id if asset.equipment_template else forms[index % len(forms)].id),
        )
        db.session.add(order)
        db.session.flush()
        _register_record(order, order.work_order_no)

    db.session.commit()
    log_kaydet(
        "Demo Veri",
        "Demo seed verileri oluşturuldu.",
        event_key="demo.seed.create",
        target_model="DemoSeedRecord",
        outcome="success",
    )
    return _summary()
