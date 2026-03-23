from demo_data import AIRPORT_PERSONNEL_COUNT, AIRPORTS, DEMO_SEED_TAG, clear_demo_data, seed_demo_data
from extensions import db
from models import DemoSeedRecord, Havalimani, InventoryAsset, Kutu, Kullanici, MaintenancePlan, SparePart, WorkOrder


def test_seed_demo_data_creates_expected_records(app):
    with app.app_context():
        summary = seed_demo_data(reset=True)

        assert summary["havalimani"] == 3
        assert summary["kullanici"] == (len(AIRPORTS) * AIRPORT_PERSONNEL_COUNT) + 2
        assert Havalimani.query.count() == 3
        assert Kullanici.query.count() == (len(AIRPORTS) * AIRPORT_PERSONNEL_COUNT) + 2
        assert InventoryAsset.query.count() > 0
        assert Kutu.query.count() > 0
        assert MaintenancePlan.query.count() > 0
        assert WorkOrder.query.count() > 0
        assert SparePart.query.count() >= 20
        assert {airport.kodu for airport in Havalimani.query.order_by(Havalimani.kodu.asc()).all()} == {"EDO", "ERZ", "KCO"}
        for airport in Havalimani.query.all():
            assert Kullanici.query.filter_by(havalimani_id=airport.id, is_deleted=False).count() >= AIRPORT_PERSONNEL_COUNT
            assert Kutu.query.filter_by(havalimani_id=airport.id, is_deleted=False).count() >= 5

        sample_asset = InventoryAsset.query.first()
        assert sample_asset is not None
        assert sample_asset.airport is not None
        assert sample_asset.legacy_material is not None
        assert sample_asset.legacy_material.kutu is not None
        assert sample_asset.asset_code.startswith("ARFF-SAR-")

        assert DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count() > 0


def test_clear_demo_data_only_removes_demo_records(app):
    with app.app_context():
        real_airport = Havalimani(ad="Gerçek Havalimanı", kodu="REAL")
        db.session.add(real_airport)
        db.session.flush()

        real_user = Kullanici(
            kullanici_adi="real.user@sarx.local",
            tam_ad="Gerçek Kullanıcı",
            rol="personel",
            havalimani_id=real_airport.id,
        )
        real_user.sifre_set("real-password")
        db.session.add(real_user)
        db.session.commit()

        seed_demo_data(reset=True)
        result = clear_demo_data()

        assert result["deleted"] > 0
        assert Havalimani.query.filter_by(kodu="REAL").first() is not None
        assert Kullanici.query.filter_by(kullanici_adi="real.user@sarx.local").first() is not None
        assert DemoSeedRecord.query.filter_by(seed_tag=DEMO_SEED_TAG).count() == 0
        assert Havalimani.query.count() == 1
        assert Kullanici.query.count() == 1
