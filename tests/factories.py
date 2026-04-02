import factory
from extensions import db
from models import (
    Announcement,
    AssignmentRecord,
    DocumentResource,
    EquipmentTemplate,
    HomeQuickLink,
    HomeSection,
    HomeSlider,
    HomeStatCard,
    InventoryAsset,
    Kutu,
    Kullanici,
    MeterDefinition,
    Havalimani,
    MaintenanceFormTemplate,
    MaintenanceInstruction,
    MaintenanceHistory,
    MaintenancePlan,
    Malzeme,
    PPEAssignmentItem,
    PPEAssignmentRecord,
    PPERecord,
    SparePart,
    SparePartStock,
    Supplier,
    WorkOrder,
)

class HavalimaniFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Havalimani
        sqlalchemy_session = db.session
    ad = factory.Sequence(lambda n: f"Birim {n}")
    kodu = factory.Sequence(lambda n: f"BRM{n}")

class KullaniciFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Kullanici
        sqlalchemy_session = db.session
    kullanici_adi = factory.Sequence(lambda n: f"test{n}@sarx.com")
    tam_ad = "Test User"
    rol = "personel"
    is_deleted = False
    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        password = kwargs.pop("password", "123456")
        obj = model_class(*args, **kwargs)
        obj.sifre_set(password)
        return obj

class KutuFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Kutu
        sqlalchemy_session = db.session
    kodu = factory.Sequence(lambda n: f"KUTU-{n}")
    havalimani = factory.SubFactory(HavalimaniFactory)

class MalzemeFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Malzeme
        sqlalchemy_session = db.session
    ad = factory.Sequence(lambda n: f"Ekipman {n}")
    seri_no = factory.Sequence(lambda n: f"SN-{n}")
    is_deleted = False
    kutu = factory.SubFactory(KutuFactory)
    # Havalimanını kutudan otomatik al
    havalimani = factory.LazyAttribute(lambda o: o.kutu.havalimani)


class MaintenanceFormTemplateFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = MaintenanceFormTemplate
        sqlalchemy_session = db.session
    name = factory.Sequence(lambda n: f"Bakim Formu {n}")
    description = "Test checklist formu"


class EquipmentTemplateFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = EquipmentTemplate
        sqlalchemy_session = db.session
    name = factory.Sequence(lambda n: f"Ekipman Sablonu {n}")
    category = "Genel"
    maintenance_period_days = 180
    is_active = True


class InventoryAssetFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = InventoryAsset
        sqlalchemy_session = db.session
    equipment_template = factory.SubFactory(EquipmentTemplateFactory)
    airport = factory.SubFactory(HavalimaniFactory)
    serial_no = factory.Sequence(lambda n: f"ASSET-SN-{n}")
    qr_code = factory.Sequence(lambda n: f"QR-{n}")
    status = "aktif"
    maintenance_state = "normal"


class MaintenancePlanFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = MaintenancePlan
        sqlalchemy_session = db.session
    name = factory.Sequence(lambda n: f"Bakim Plani {n}")
    asset = factory.SubFactory(InventoryAssetFactory)
    period_days = 30
    is_active = True


class MaintenanceInstructionFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = MaintenanceInstruction
        sqlalchemy_session = db.session
    equipment_template = factory.SubFactory(EquipmentTemplateFactory)
    title = factory.Sequence(lambda n: f"Bakım Talimatı {n}")
    description = "Periyodik kontrol adımları"
    is_active = True


class WorkOrderFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = WorkOrder
        sqlalchemy_session = db.session
    work_order_no = factory.Sequence(lambda n: f"WO-TEST-{n}")
    asset = factory.SubFactory(InventoryAssetFactory)
    maintenance_type = "bakim"
    description = "Test iş emri"
    created_user = factory.SubFactory(KullaniciFactory, rol="sistem_sorumlusu")
    status = "acik"
    priority = "orta"


class AssignmentRecordFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = AssignmentRecord
        sqlalchemy_session = db.session
    assignment_no = factory.Sequence(lambda n: f"ZMT-{20260000 + n}")
    status = "active"


class PPEAssignmentRecordFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = PPEAssignmentRecord
        sqlalchemy_session = db.session
    assignment_no = factory.Sequence(lambda n: f"KKD-ZMT-{20260000 + n}")
    delivered_by = factory.SubFactory(KullaniciFactory)
    delivered_by_name = factory.LazyAttribute(lambda o: o.delivered_by.tam_ad)
    recipient_user = factory.SubFactory(KullaniciFactory)
    airport = factory.LazyAttribute(lambda o: o.recipient_user.havalimani or HavalimaniFactory())
    status = "active"


class PPERecordFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = PPERecord
        sqlalchemy_session = db.session
    user = factory.SubFactory(KullaniciFactory)
    airport = factory.LazyAttribute(lambda o: o.user.havalimani or HavalimaniFactory())
    item_name = "Baret"
    quantity = 1
    status = "aktif"


class PPEAssignmentItemFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = PPEAssignmentItem
        sqlalchemy_session = db.session
    assignment = factory.SubFactory(PPEAssignmentRecordFactory)
    ppe_record = factory.SubFactory(PPERecordFactory)
    item_name = factory.LazyAttribute(lambda o: o.ppe_record.item_name)
    category = factory.LazyAttribute(lambda o: o.ppe_record.category)
    subcategory = factory.LazyAttribute(lambda o: o.ppe_record.subcategory)
    quantity = 1
    unit = "adet"


class MaintenanceHistoryFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = MaintenanceHistory
        sqlalchemy_session = db.session
    asset = factory.SubFactory(InventoryAssetFactory)
    maintenance_type = "bakim"
    result = "Tamamlandi"


class HomeSliderFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = HomeSlider
        sqlalchemy_session = db.session
    title = factory.Sequence(lambda n: f"Slider {n}")
    subtitle = "Kurumsal operasyon altyapısı"
    description = "Acil müdahale ve koordinasyon odağı"
    image_url = "https://images.unsplash.com/photo-1543269664-7eef42226a21?auto=format&fit=crop&w=1200&q=80"
    order_index = 0
    is_active = True


class HomeSectionFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = HomeSection
        sqlalchemy_session = db.session
    section_key = "about"
    title = factory.Sequence(lambda n: f"Bölüm {n}")
    content = "Kurumsal bilgi"
    order_index = 0
    is_active = True


class AnnouncementFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Announcement
        sqlalchemy_session = db.session
    title = factory.Sequence(lambda n: f"Duyuru {n}")
    slug = factory.Sequence(lambda n: f"duyuru-{n}")
    summary = "Kısa özet"
    content = "Detay metni"
    is_published = True


class DocumentResourceFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = DocumentResource
        sqlalchemy_session = db.session
    title = factory.Sequence(lambda n: f"Doküman {n}")
    description = "Doküman açıklaması"
    file_path = "/docs/ornek.pdf"
    category = "Form"
    order_index = 0
    is_active = True


class HomeStatCardFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = HomeStatCard
        sqlalchemy_session = db.session
    title = factory.Sequence(lambda n: f"İstatistik {n}")
    value_text = "24/7"
    subtitle = "Hazır ekip"
    order_index = 0
    is_active = True


class HomeQuickLinkFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = HomeQuickLink
        sqlalchemy_session = db.session
    title = factory.Sequence(lambda n: f"Hızlı Link {n}")
    description = "Kısa açıklama"
    link_url = "#"
    order_index = 0
    is_active = True


class SupplierFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Supplier
        sqlalchemy_session = db.session
    name = factory.Sequence(lambda n: f"Tedarikci {n}")
    is_active = True


class SparePartFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = SparePart
        sqlalchemy_session = db.session
    part_code = factory.Sequence(lambda n: f"PART-{n}")
    title = factory.Sequence(lambda n: f"Yedek Parca {n}")
    category = "Genel"
    unit = "adet"
    min_stock_level = 2
    critical_level = 1
    is_active = True


class SparePartStockFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = SparePartStock
        sqlalchemy_session = db.session
    spare_part = factory.SubFactory(SparePartFactory)
    airport_stock = factory.SubFactory(HavalimaniFactory)
    quantity_on_hand = 10
    quantity_reserved = 0
    reorder_point = 3
    is_active = True


class MeterDefinitionFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = MeterDefinition
        sqlalchemy_session = db.session
    name = factory.Sequence(lambda n: f"Sayaç {n}")
    meter_type = "hours"
    unit = "h"
    equipment_template = factory.SubFactory(EquipmentTemplateFactory)
    is_active = True
