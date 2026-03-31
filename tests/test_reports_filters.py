from extensions import db
from tests.factories import EquipmentTemplateFactory, HavalimaniFactory, InventoryAssetFactory, KullaniciFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_reports_filters_apply_airport_and_category(client, app):
    with app.app_context():
        airport_one = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        airport_two = HavalimaniFactory(ad="Trabzon Havalimanı", kodu="TZX")
        template_one = EquipmentTemplateFactory(name="Hidrolik Kesici", category="Kurtarma")
        template_two = EquipmentTemplateFactory(name="Gaz Ölçüm Cihazı", category="Olcum")
        asset_one = InventoryAssetFactory(equipment_template=template_one, airport=airport_one, serial_no="ERZ-001")
        asset_two = InventoryAssetFactory(equipment_template=template_two, airport=airport_two, serial_no="TZX-001")
        user = KullaniciFactory(rol="sahip", havalimani=airport_one, is_deleted=False)
        db.session.add_all([airport_one, airport_two, template_one, template_two, asset_one, asset_two, user])
        db.session.commit()
        user_id = user.id
        airport_one_id = airport_one.id

    _login(client, user_id)
    response = client.get(f"/reports?report=inventory&airport_id={airport_one_id}&category=Kurtarma")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Hidrolik Kesici" in html
    assert "Erzurum Havalimanı" in html
    assert "Gaz Ölçüm Cihazı" not in html
    assert "TZX-001" not in html
    assert 'class="report-toolbar"' in html
    assert 'class="report-tabs-shell"' in html
    assert 'class="panel report-filters-panel"' in html


def test_reports_filters_match_turkish_category_variants(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="İzmir Çiğli Havalimanı", kodu="IGL")
        template_match = EquipmentTemplateFactory(name="Gaz Ölçüm Cihazı", category="Ölçüm")
        template_other = EquipmentTemplateFactory(name="Termal Kamera", category="Optik")
        asset_match = InventoryAssetFactory(equipment_template=template_match, airport=airport, serial_no="IGL-001")
        asset_other = InventoryAssetFactory(equipment_template=template_other, airport=airport, serial_no="IGL-002")
        user = KullaniciFactory(rol="sahip", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, template_match, template_other, asset_match, asset_other, user])
        db.session.commit()
        user_id = user.id
        airport_id = airport.id

    _login(client, user_id)
    response = client.get(f"/reports?report=inventory&airport_id={airport_id}&category=olcum")
    html = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Gaz Ölçüm Cihazı" in html
    assert "Termal Kamera" not in html


def test_reports_reuses_single_snapshot_per_request(client, app, monkeypatch):
    from routes import reports as reports_module
    import reporting as reporting_module

    with app.app_context():
        airport = HavalimaniFactory(ad="Samsun Havalimanı", kodu="SZF")
        template = EquipmentTemplateFactory(name="Kesici", category="Kurtarma")
        asset = InventoryAssetFactory(equipment_template=template, airport=airport, serial_no="SZF-001")
        user = KullaniciFactory(rol="sahip", havalimani=airport, is_deleted=False)
        db.session.add_all([airport, template, asset, user])
        db.session.commit()
        user_id = user.id

    real_build_operational_snapshot = reporting_module.build_operational_snapshot
    call_count = {"value": 0}

    def counting_snapshot(user, filters):
        call_count["value"] += 1
        return real_build_operational_snapshot(user, filters)

    monkeypatch.setattr(reporting_module, "build_operational_snapshot", counting_snapshot)
    monkeypatch.setattr(reports_module, "build_operational_snapshot", counting_snapshot)

    _login(client, user_id)
    response = client.get("/reports?report=inventory")

    assert response.status_code == 200
    assert call_count["value"] == 1
