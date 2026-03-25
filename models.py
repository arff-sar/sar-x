from extensions import db
from datetime import datetime, timedelta
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import pytz
from decorators import (
    CANONICAL_ROLE_ADMIN,
    CANONICAL_ROLE_SYSTEM,
    CANONICAL_ROLE_TEAM_LEAD,
    get_effective_role,
    get_effective_permissions,
)

# --- ZAMAN AYARLARI ---
TR_TZ = pytz.timezone('Europe/Istanbul')

TR_UPPER_MAP = str.maketrans("çğıöşüi", "ÇĞIÖŞÜİ")

def get_tr_now():
    """İstanbul yerel saatini döner."""
    return datetime.now(TR_TZ)

# --- MİXİNLER (YENİLENMİŞ) ---

class TimestampMixin:
    """Tüm tablolara otomatik yerel tarih ekler."""
    created_at = db.Column(db.DateTime, default=get_tr_now)
    updated_at = db.Column(db.DateTime, default=get_tr_now, onupdate=get_tr_now)

class SoftDeleteMixin:
    """✅ YENİ: Verilerin fiziksel olarak silinmesini engeller, arşivler."""
    is_deleted = db.Column(db.Boolean, default=False, index=True) # Hızlı filtreleme için indekslendi
    deleted_at = db.Column(db.DateTime, nullable=True)

    def soft_delete(self, commit=False):
        self.is_deleted = True
        self.deleted_at = get_tr_now()
        if commit:
            db.session.commit()

# --- ANA MODELLER ---

class Havalimani(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'havalimani'
    id = db.Column(db.Integer, primary_key=True)
    ad = db.Column(db.String(100), nullable=False)
    kodu = db.Column(db.String(10), nullable=False, unique=True)
    drive_folder_id = db.Column(db.String(255), nullable=True, index=True)
    
    personeller = db.relationship('Kullanici', backref='havalimani', lazy=True)
    kutular = db.relationship('Kutu', backref='havalimani', lazy=True)
    malzemeler = db.relationship('Malzeme', backref='havalimani', lazy=True)
    assets = db.relationship('InventoryAsset', backref='airport', lazy=True)
    maintenance_plans = db.relationship('MaintenancePlan', backref='airport_owner', lazy=True)
    spare_part_stocks = db.relationship('SparePartStock', backref='airport_stock', lazy=True)
    tatbikat_belgeleri = db.relationship('TatbikatBelgesi', backref='havalimani', lazy=True)

class Kullanici(db.Model, UserMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'kullanici'
    id = db.Column(db.Integer, primary_key=True)
    kullanici_adi = db.Column(db.String(50), unique=True, nullable=False)
    sifre_hash = db.Column(db.String(256))
    tam_ad = db.Column(db.String(100), nullable=False)
    
    # ✅ PERFORMANS: Rol ve Havalimanı ID indekslendi
    rol = db.Column(db.String(20), nullable=False, default='personel', index=True) 
    havalimani_id = db.Column(db.Integer, db.ForeignKey('havalimani.id'), nullable=True, index=True)
    telefon_numarasi = db.Column(db.String(32))
    
    sertifika_tarihi = db.Column(db.Date)
    uzmanlik_alani = db.Column(db.String(100))
    kayit_tarihi = db.Column(db.DateTime, default=get_tr_now)
    assigned_work_orders = db.relationship(
        'WorkOrder',
        foreign_keys='WorkOrder.assigned_user_id',
        backref='assigned_user',
        lazy=True
    )
    created_work_orders = db.relationship(
        'WorkOrder',
        foreign_keys='WorkOrder.created_user_id',
        backref='created_user',
        lazy=True
    )

    @property
    def is_sahip(self):
        return get_effective_role(self) == CANONICAL_ROLE_SYSTEM

    @property
    def is_genel_mudurluk(self):
        return get_effective_role(self) == CANONICAL_ROLE_ADMIN

    @property
    def is_editor(self):
        permissions = get_effective_permissions(self)
        return "homepage.view" in permissions and "inventory.view" not in permissions

    @property
    def can_edit(self):
        return 'inventory.edit' in get_effective_permissions(self)

    @property
    def can_view_all(self):
        permissions = get_effective_permissions(self)
        return 'settings.manage' in permissions or 'logs.view' in permissions

    @property
    def can_manage_homepage(self):
        return 'homepage.view' in get_effective_permissions(self)

    @property
    def can_manage_users(self):
        return 'users.manage' in get_effective_permissions(self)

    @property
    def is_airport_manager(self):
        return get_effective_role(self) == CANONICAL_ROLE_TEAM_LEAD

    @property
    def effective_permissions(self):
        return sorted(get_effective_permissions(self))

    def sifre_set(self, sifre):
        self.sifre_hash = generate_password_hash(sifre, method='pbkdf2:sha256')

    def sifre_kontrol(self, sifre):
        return check_password_hash(self.sifre_hash, sifre)

class Kutu(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'kutu'
    id = db.Column(db.Integer, primary_key=True)
    kodu = db.Column(db.String(50), unique=True, nullable=False)
    marka = db.Column(db.String(120))
    konum = db.Column(db.String(100)) 
    havalimani_id = db.Column(db.Integer, db.ForeignKey('havalimani.id'), nullable=False, index=True)
    
    malzemeler = db.relationship('Malzeme', backref='kutu', lazy=True)

    @property
    def qr_serial(self):
        return f"{self.id:06d}" if self.id else None

    @property
    def qr_code_label(self):
        return self.kodu or (f"KUTU-{self.qr_serial}" if self.qr_serial else "KUTU")

    @property
    def qr_label_airport_name(self):
        if self.havalimani and self.havalimani.ad:
            return self.havalimani.ad.translate(TR_UPPER_MAP).upper()
        return "HAVALIMANI TANIMSIZ"

    @property
    def qr_payload(self):
        return f"BOX::{self.id}::{self.qr_code_label}::{self.qr_label_airport_name}"

    @property
    def active_materials(self):
        return [item for item in self.malzemeler if not item.is_deleted]

class Malzeme(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'malzeme'
    id = db.Column(db.Integer, primary_key=True)
    ad = db.Column(db.String(100), nullable=False)
    seri_no = db.Column(db.String(100), unique=True)
    teknik_ozellikler = db.Column(db.Text)
    stok_miktari = db.Column(db.Integer, default=1)
    
    # ✅ PERFORMANS: Durum ve Bakım tarihi raporlar için indekslendi
    durum = db.Column(db.String(20), default='Aktif', index=True) 
    kritik_mi = db.Column(db.Boolean, default=False)
    
    son_bakim_tarihi = db.Column(db.Date)
    gelecek_bakim_tarihi = db.Column(db.Date, index=True)
    kalibrasyon_tarihi = db.Column(db.Date)
    
    kutu_id = db.Column(db.Integer, db.ForeignKey('kutu.id'), nullable=False, index=True)
    havalimani_id = db.Column(db.Integer, db.ForeignKey('havalimani.id'), nullable=False, index=True)
    
    bakim_kayitlari = db.relationship('BakimKaydi', backref='malzeme', lazy=True, cascade="all, delete-orphan")
    linked_asset = db.relationship('InventoryAsset', backref='legacy_material', uselist=False)

class BakimKaydi(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'bakim_kaydi'
    id = db.Column(db.Integer, primary_key=True)
    malzeme_id = db.Column(db.Integer, db.ForeignKey('malzeme.id'), nullable=False, index=True)
    yapan_personel_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'))
    islem_notu = db.Column(db.Text, nullable=False)
    maliyet = db.Column(db.Float, default=0.0)

class IslemLog(db.Model):
    __tablename__ = 'islem_log'
    id = db.Column(db.Integer, primary_key=True)
    kullanici_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    islem_tipi = db.Column(db.String(50), nullable=False)
    event_key = db.Column(db.String(120), index=True)
    detay = db.Column(db.Text)
    target_model = db.Column(db.String(80), index=True)
    target_id = db.Column(db.Integer, index=True)
    outcome = db.Column(db.String(20), default='success', index=True)
    error_code = db.Column(db.String(32), nullable=True, index=True)
    title = db.Column(db.String(180), nullable=True)
    user_message = db.Column(db.String(255), nullable=True)
    owner_message = db.Column(db.Text, nullable=True)
    module = db.Column(db.String(24), nullable=True, index=True)
    severity = db.Column(db.String(20), nullable=True, index=True)
    exception_type = db.Column(db.String(120), nullable=True)
    exception_message = db.Column(db.Text, nullable=True)
    traceback_summary = db.Column(db.Text, nullable=True)
    route = db.Column(db.String(255), nullable=True)
    method = db.Column(db.String(12), nullable=True)
    request_id = db.Column(db.String(64), nullable=True, index=True)
    user_email = db.Column(db.String(150), nullable=True)
    resolved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    resolution_note = db.Column(db.Text, nullable=True)
    ip_adresi = db.Column(db.String(45)) 
    user_agent = db.Column(db.String(200))
    ip_address = db.Column(db.String(45), nullable=True)
    zaman = db.Column(db.DateTime, default=get_tr_now, index=True)

    yapan_kullanici = db.relationship('Kullanici', backref='loglar')

    @property
    def created_at(self):
        return self.zaman

    @property
    def short_user_message(self):
        return (self.user_message or self.detay or "").strip()


class AuthLockout(db.Model, TimestampMixin):
    __tablename__ = 'auth_lockout'

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(180), nullable=False, unique=True, index=True)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True, index=True)
    last_failed_at = db.Column(db.DateTime, nullable=True)
    last_ip = db.Column(db.String(45), nullable=True)


class LoginVisualChallenge(db.Model, TimestampMixin):
    __tablename__ = "login_visual_challenge"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(96), nullable=False, unique=True, index=True)
    code = db.Column(db.String(12), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    invalidated_at = db.Column(db.DateTime, nullable=True, index=True)
    last_rendered_at = db.Column(db.DateTime, nullable=True)


class Role(db.Model, TimestampMixin):
    __tablename__ = 'role'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), nullable=False, unique=True, index=True)
    label = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    scope = db.Column(db.String(20), default='global', nullable=False)
    is_system = db.Column(db.Boolean, default=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    permissions = db.relationship('RolePermission', backref='role', lazy=True, cascade='all, delete-orphan')


class Permission(db.Model, TimestampMixin):
    __tablename__ = 'permission'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), nullable=False, unique=True, index=True)
    label = db.Column(db.String(160), nullable=False)
    module = db.Column(db.String(40), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    roles = db.relationship('RolePermission', backref='permission', lazy=True, cascade='all, delete-orphan')


class RolePermission(db.Model, TimestampMixin):
    __tablename__ = 'role_permission'

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), nullable=False, index=True)
    permission_id = db.Column(db.Integer, db.ForeignKey('permission.id'), nullable=False, index=True)
    is_allowed = db.Column(db.Boolean, default=True, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint('role_id', 'permission_id', name='uq_role_permission'),
    )


class UserPermissionOverride(db.Model, TimestampMixin):
    __tablename__ = 'user_permission_override'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=False, index=True)
    permission_key = db.Column(db.String(80), nullable=False, index=True)
    is_allowed = db.Column(db.Boolean, default=True, nullable=False, index=True)

    user = db.relationship('Kullanici', backref='permission_overrides')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'permission_key', name='uq_user_permission_override'),
    )


class ApprovalRequest(db.Model, TimestampMixin):
    __tablename__ = 'approval_request'

    id = db.Column(db.Integer, primary_key=True)
    approval_type = db.Column(db.String(80), nullable=False, index=True)
    target_model = db.Column(db.String(80), nullable=False, index=True)
    target_id = db.Column(db.Integer, nullable=True, index=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=False, index=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    request_payload = db.Column(db.Text)
    review_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_tr_now, index=True)
    reviewed_at = db.Column(db.DateTime, nullable=True, index=True)

    requested_by = db.relationship('Kullanici', foreign_keys=[requested_by_id], backref='approval_requests')
    approved_by = db.relationship('Kullanici', foreign_keys=[approved_by_id])


class Notification(db.Model, TimestampMixin):
    __tablename__ = 'notification'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=False, index=True)
    type = db.Column(db.String(80), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link_url = db.Column(db.String(300))
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    severity = db.Column(db.String(20), default='info', nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=get_tr_now, index=True)

    user = db.relationship('Kullanici', backref='notifications')


class DemoSeedRecord(db.Model, TimestampMixin):
    __tablename__ = 'demo_seed_record'

    id = db.Column(db.Integer, primary_key=True)
    seed_tag = db.Column(db.String(60), nullable=False, index=True, default='demo_seed')
    model_name = db.Column(db.String(80), nullable=False, index=True)
    record_id = db.Column(db.Integer, nullable=False, index=True)
    record_label = db.Column(db.String(180))

    __table_args__ = (
        db.UniqueConstraint('seed_tag', 'model_name', 'record_id', name='uq_demo_seed_record'),
    )


# --- BAKIM / VARLIK YÖNETİM MODELLERİ ---

class MaintenanceFormTemplate(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'maintenance_form_template'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    fields = db.relationship(
        'MaintenanceFormField',
        backref='form_template',
        lazy=True,
        cascade='all, delete-orphan',
        order_by='MaintenanceFormField.order_index'
    )


class MaintenanceFormField(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'maintenance_form_field'

    id = db.Column(db.Integer, primary_key=True)
    form_template_id = db.Column(
        db.Integer,
        db.ForeignKey('maintenance_form_template.id'),
        nullable=False,
        index=True
    )
    field_key = db.Column(db.String(100), nullable=False)
    label = db.Column(db.String(150), nullable=False)
    field_type = db.Column(db.String(30), nullable=False, default='text')
    is_required = db.Column(db.Boolean, default=False, nullable=False)
    order_index = db.Column(db.Integer, default=0, nullable=False)
    options_json = db.Column(db.Text)
    placeholder = db.Column(db.String(150))


class EquipmentTemplate(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'equipment_template'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    category = db.Column(db.String(80), index=True)
    brand = db.Column(db.String(80))
    model_code = db.Column(db.String(80))
    description = db.Column(db.Text)
    technical_specs = db.Column(db.Text)
    manufacturer = db.Column(db.String(120))
    maintenance_period_days = db.Column(db.Integer, default=180)
    maintenance_period_months = db.Column(db.Integer, default=6)
    criticality_level = db.Column(db.String(20), default='normal', index=True)
    default_maintenance_form_id = db.Column(
        db.Integer,
        db.ForeignKey('maintenance_form_template.id'),
        nullable=True
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    default_maintenance_form = db.relationship(
        'MaintenanceFormTemplate',
        foreign_keys=[default_maintenance_form_id]
    )
    assets = db.relationship('InventoryAsset', backref='equipment_template', lazy=True)
    maintenance_plans = db.relationship('MaintenancePlan', backref='equipment_template', lazy=True)


class InventoryCategory(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "inventory_category"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True, index=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("kullanici.id"), nullable=True, index=True)

    created_by = db.relationship("Kullanici", foreign_keys=[created_by_user_id])


class InventoryBulkImportJob(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "inventory_bulk_import_job"

    id = db.Column(db.Integer, primary_key=True)
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey("kullanici.id"), nullable=False, index=True)
    havalimani_id = db.Column(db.Integer, db.ForeignKey("havalimani.id"), nullable=True, index=True)
    source_filename = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="completed", index=True)
    total_rows = db.Column(db.Integer, nullable=False, default=0)
    success_rows = db.Column(db.Integer, nullable=False, default=0)
    failed_rows = db.Column(db.Integer, nullable=False, default=0)
    summary_note = db.Column(db.Text)

    requested_by = db.relationship("Kullanici", foreign_keys=[requested_by_user_id])
    airport = db.relationship("Havalimani", foreign_keys=[havalimani_id])
    row_results = db.relationship(
        "InventoryBulkImportRowResult",
        backref="job",
        lazy=True,
        cascade="all, delete-orphan",
    )


class InventoryBulkImportRowResult(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "inventory_bulk_import_row_result"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("inventory_bulk_import_job.id"), nullable=False, index=True)
    row_no = db.Column(db.Integer, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, index=True)
    message = db.Column(db.Text)
    serial_no = db.Column(db.String(120), index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("inventory_asset.id"), nullable=True, index=True)

    asset = db.relationship("InventoryAsset", foreign_keys=[asset_id])


class InventoryAsset(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'inventory_asset'

    id = db.Column(db.Integer, primary_key=True)
    equipment_template_id = db.Column(
        db.Integer,
        db.ForeignKey('equipment_template.id'),
        nullable=False,
        index=True
    )
    havalimani_id = db.Column(
        db.Integer,
        db.ForeignKey('havalimani.id'),
        nullable=False,
        index=True
    )
    legacy_material_id = db.Column(
        db.Integer,
        db.ForeignKey('malzeme.id'),
        nullable=True,
        index=True
    )
    parent_asset_id = db.Column(
        db.Integer,
        db.ForeignKey('inventory_asset.id'),
        nullable=True,
        index=True
    )

    serial_no = db.Column(db.String(120), index=True)
    asset_type = db.Column(db.String(30), default="equipment", index=True)
    qr_code = db.Column(db.String(150), unique=True, index=True)
    asset_tag = db.Column(db.String(120), index=True)
    is_demirbas = db.Column(db.Boolean, default=False, nullable=False, index=True)
    unit_count = db.Column(db.Integer, default=1)
    depot_location = db.Column(db.String(150))
    status = db.Column(db.String(30), default='aktif', index=True)
    maintenance_state = db.Column(db.String(30), default='normal', index=True)

    last_maintenance_date = db.Column(db.Date)
    next_maintenance_date = db.Column(db.Date, index=True)
    calibration_required = db.Column(db.Boolean, default=False, nullable=False, index=True)
    calibration_period_days = db.Column(db.Integer)
    last_calibration_date = db.Column(db.Date)
    next_calibration_date = db.Column(db.Date)
    acquired_date = db.Column(db.Date)
    warranty_end_date = db.Column(db.Date)
    manual_url = db.Column(db.String(500))
    notes = db.Column(db.Text)

    maintenance_period_days = db.Column(db.Integer)
    maintenance_period_months = db.Column(db.Integer, default=6)
    is_critical = db.Column(db.Boolean, default=False, index=True)
    last_meter_sync_at = db.Column(db.DateTime, nullable=True, index=True)
    calibration_counter = db.Column(db.Integer, default=0)

    parent_asset = db.relationship(
        'InventoryAsset',
        remote_side=[id],
        backref=db.backref('child_assets', lazy='select'),
        foreign_keys=[parent_asset_id],
    )
    maintenance_plans = db.relationship('MaintenancePlan', backref='asset', lazy=True)
    work_orders = db.relationship('WorkOrder', backref='asset', lazy=True, cascade='all, delete-orphan')
    maintenance_histories = db.relationship(
        'MaintenanceHistory',
        backref='asset',
        lazy=True,
        cascade='all, delete-orphan'
    )
    meter_readings = db.relationship('AssetMeterReading', backref='asset', lazy=True, cascade='all, delete-orphan')
    meter_definitions = db.relationship('MeterDefinition', backref='asset_owner', lazy=True)
    trigger_rules = db.relationship('MaintenanceTriggerRule', backref='asset_owner', lazy=True)
    operational_state = db.relationship(
        'AssetOperationalState',
        backref='asset',
        uselist=False,
        lazy=True,
        cascade='all, delete-orphan',
    )
    calibration_schedules = db.relationship('CalibrationSchedule', backref='asset', lazy=True, cascade='all, delete-orphan')
    calibration_records = db.relationship('CalibrationRecord', backref='asset', lazy=True, cascade='all, delete-orphan')
    spare_part_links = db.relationship('AssetSparePartLink', backref='asset', lazy=True, cascade='all, delete-orphan')

    @property
    def qr_serial(self):
        return f"{self.id:06d}" if self.id else None

    @property
    def asset_code(self):
        serial = self.qr_serial
        return f"ARFF-SAR-{serial}" if serial else None

    @property
    def qr_label_airport_name(self):
        if self.airport and self.airport.ad:
            return self.airport.ad.translate(TR_UPPER_MAP).upper()
        return "HAVALIMANI TANIMSIZ"

    @property
    def lifecycle_status(self):
        from extensions import table_exists

        if table_exists("asset_operational_state") and self.operational_state and self.operational_state.lifecycle_status:
            return self.operational_state.lifecycle_status
        if self.status == "hurda":
            return "disposed"
        if self.status == "pasif":
            return "decommissioned"
        if self.status == "bakimda":
            return "in_maintenance"
        return "active"

    @property
    def under_warranty(self):
        if not self.warranty_end_date:
            return False
        return self.warranty_end_date >= get_tr_now().date()


class AssetOperationalState(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'asset_operational_state'

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('inventory_asset.id'), nullable=False, unique=True, index=True)
    lifecycle_status = db.Column(db.String(30), nullable=False, default='active', index=True)
    warranty_start = db.Column(db.Date)
    service_provider = db.Column(db.String(150))
    service_note = db.Column(db.Text)
    last_service_date = db.Column(db.Date)
    lifecycle_note = db.Column(db.Text)
    transfer_reference = db.Column(db.String(120))
    last_transfer_at = db.Column(db.DateTime)
    disposed_at = db.Column(db.DateTime)
    out_of_service_at = db.Column(db.DateTime)

    @property
    def warranty_end(self):
        return self.asset.warranty_end_date if self.asset else None

    @property
    def under_warranty(self):
        return bool(self.asset and self.asset.under_warranty)


class MaintenancePlan(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'maintenance_plan'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    equipment_template_id = db.Column(
        db.Integer,
        db.ForeignKey('equipment_template.id'),
        nullable=True,
        index=True
    )
    asset_id = db.Column(
        db.Integer,
        db.ForeignKey('inventory_asset.id'),
        nullable=True,
        index=True
    )
    owner_airport_id = db.Column(
        db.Integer,
        db.ForeignKey('havalimani.id'),
        nullable=True,
        index=True
    )
    period_days = db.Column(db.Integer, nullable=False, default=30)
    start_date = db.Column(db.Date)
    last_maintenance_date = db.Column(db.Date)
    next_due_date = db.Column(db.Date, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    notes = db.Column(db.Text)

    def recalculate_next_due_date(self, reference_date=None):
        base = reference_date or self.last_maintenance_date or self.start_date or get_tr_now().date()
        self.next_due_date = base + timedelta(days=max(self.period_days or 1, 1))
        return self.next_due_date


class WorkOrder(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'work_order'

    id = db.Column(db.Integer, primary_key=True)
    work_order_no = db.Column(db.String(30), nullable=False, unique=True, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('inventory_asset.id'), nullable=False, index=True)
    maintenance_type = db.Column(db.String(30), nullable=False, default='bakim', index=True)
    work_order_type = db.Column(db.String(30), nullable=False, default='preventive', index=True)
    source_type = db.Column(db.String(30), nullable=False, default='manual', index=True)
    description = db.Column(db.Text, nullable=False)
    opened_at = db.Column(db.DateTime, default=get_tr_now, nullable=False)
    target_date = db.Column(db.Date, index=True)
    sla_target_at = db.Column(db.DateTime, nullable=True, index=True)
    completed_at = db.Column(db.DateTime)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    created_user_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='acik', index=True)
    priority = db.Column(db.String(20), nullable=False, default='orta', index=True)
    result = db.Column(db.Text)
    used_parts = db.Column(db.Text)
    labor_hours = db.Column(db.Float)
    labor_minutes = db.Column(db.Integer)
    downtime_minutes = db.Column(db.Integer)
    extra_notes = db.Column(db.Text)
    failure_code = db.Column(db.String(80))
    root_cause = db.Column(db.Text)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    completed_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    completion_notes = db.Column(db.Text)
    verification_status = db.Column(db.String(20), default='beklemede', index=True)
    is_repeat_failure = db.Column(db.Boolean, default=False, index=True)
    checklist_template_id = db.Column(
        db.Integer,
        db.ForeignKey('maintenance_form_template.id'),
        nullable=True
    )

    checklist_template = db.relationship('MaintenanceFormTemplate', foreign_keys=[checklist_template_id])
    approved_by = db.relationship('Kullanici', foreign_keys=[approved_by_id], post_update=True)
    completed_by = db.relationship('Kullanici', foreign_keys=[completed_by_id], post_update=True)
    checklist_responses = db.relationship(
        'WorkOrderChecklistResponse',
        backref='work_order',
        lazy=True,
        cascade='all, delete-orphan'
    )
    part_usages = db.relationship(
        'WorkOrderPartUsage',
        backref='work_order',
        lazy=True,
        cascade='all, delete-orphan'
    )
    maintenance_history = db.relationship('MaintenanceHistory', backref='work_order', uselist=False)


class WorkOrderChecklistResponse(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'work_order_checklist_response'

    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_order.id'), nullable=False, index=True)
    field_id = db.Column(db.Integer, db.ForeignKey('maintenance_form_field.id'), nullable=True, index=True)
    field_key = db.Column(db.String(100), nullable=False)
    field_label = db.Column(db.String(150), nullable=False)
    response_value = db.Column(db.Text)
    responded_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    responded_at = db.Column(db.DateTime, default=get_tr_now, nullable=False)
    evidence_path = db.Column(db.String(500))
    approval_note = db.Column(db.Text)
    is_failure = db.Column(db.Boolean, default=False, index=True)

    responded_by = db.relationship('Kullanici')


class MaintenanceHistory(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'maintenance_history'

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('inventory_asset.id'), nullable=False, index=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_order.id'), nullable=True, index=True)
    performed_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    maintenance_type = db.Column(db.String(30), nullable=False, default='bakim')
    performed_at = db.Column(db.DateTime, default=get_tr_now, nullable=False, index=True)
    result = db.Column(db.Text)
    checklist_snapshot = db.Column(db.Text)
    notes = db.Column(db.Text)
    next_maintenance_date = db.Column(db.Date)
    inspection_score = db.Column(db.Float)
    inspection_summary = db.Column(db.Text)
    source_type = db.Column(db.String(30), default='manual')

    performed_by = db.relationship('Kullanici')


class Supplier(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'supplier'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True, index=True)
    contact_name = db.Column(db.String(120))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(150))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    spare_parts = db.relationship('SparePart', backref='supplier', lazy=True)


class SparePart(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'spare_part'

    id = db.Column(db.Integer, primary_key=True)
    part_code = db.Column(db.String(80), nullable=False, unique=True, index=True)
    title = db.Column(db.String(180), nullable=False, index=True)
    category = db.Column(db.String(80), index=True)
    compatible_asset_type = db.Column(db.String(120))
    manufacturer = db.Column(db.String(120))
    model_code = db.Column(db.String(120))
    description = db.Column(db.Text)
    unit = db.Column(db.String(20), default='adet')
    min_stock_level = db.Column(db.Float, default=0)
    critical_level = db.Column(db.Float, default=0)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    stocks = db.relationship('SparePartStock', backref='spare_part', lazy=True, cascade='all, delete-orphan')
    usages = db.relationship('WorkOrderPartUsage', backref='spare_part', lazy=True, cascade='all, delete-orphan')
    asset_links = db.relationship('AssetSparePartLink', backref='spare_part', lazy=True, cascade='all, delete-orphan')


class AssetSparePartLink(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'asset_spare_part_link'

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('inventory_asset.id'), nullable=False, index=True)
    spare_part_id = db.Column(db.Integer, db.ForeignKey('spare_part.id'), nullable=False, index=True)
    quantity_required = db.Column(db.Float, default=1, nullable=False)
    note = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint('asset_id', 'spare_part_id', name='uq_asset_spare_part_link'),
    )


class SparePartStock(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'spare_part_stock'

    id = db.Column(db.Integer, primary_key=True)
    spare_part_id = db.Column(db.Integer, db.ForeignKey('spare_part.id'), nullable=False, index=True)
    airport_id = db.Column(db.Integer, db.ForeignKey('havalimani.id'), nullable=False, index=True)
    quantity_on_hand = db.Column(db.Float, default=0, nullable=False)
    quantity_reserved = db.Column(db.Float, default=0, nullable=False)
    reorder_point = db.Column(db.Float, default=0, nullable=False)
    shelf_location = db.Column(db.String(120))
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint('spare_part_id', 'airport_id', name='uq_spare_part_airport_stock'),
    )

    @property
    def available_quantity(self):
        return float(self.quantity_on_hand or 0) - float(self.quantity_reserved or 0)

    def reserve(self, quantity):
        amount = max(float(quantity or 0), 0)
        self.quantity_reserved = max(float(self.quantity_reserved or 0) + amount, 0)
        return self.quantity_reserved

    def consume(self, quantity):
        amount = max(float(quantity or 0), 0)
        self.quantity_on_hand = max(float(self.quantity_on_hand or 0) - amount, 0)
        self.quantity_reserved = max(float(self.quantity_reserved or 0) - amount, 0)
        return self.quantity_on_hand

    def is_low_stock(self):
        threshold = self.reorder_point if self.reorder_point is not None else self.spare_part.min_stock_level
        return self.available_quantity <= float(threshold or 0)


class ConsumableItem(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'consumable_item'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), nullable=False, unique=True, index=True)
    title = db.Column(db.String(180), nullable=False, index=True)
    category = db.Column(db.String(80), index=True)
    unit = db.Column(db.String(20), default='adet')
    min_stock_level = db.Column(db.Float, default=0)
    critical_level = db.Column(db.Float, default=0)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    movements = db.relationship('ConsumableStockMovement', backref='consumable', lazy=True, cascade='all, delete-orphan')


class ConsumableStockMovement(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'consumable_stock_movement'

    id = db.Column(db.Integer, primary_key=True)
    consumable_id = db.Column(db.Integer, db.ForeignKey('consumable_item.id'), nullable=False, index=True)
    airport_id = db.Column(db.Integer, db.ForeignKey('havalimani.id'), nullable=False, index=True)
    kutu_id = db.Column(db.Integer, db.ForeignKey('kutu.id'), nullable=True, index=True)
    movement_type = db.Column(db.String(20), nullable=False, index=True)
    quantity = db.Column(db.Float, nullable=False, default=0)
    reference_note = db.Column(db.Text)
    performed_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)

    airport = db.relationship('Havalimani')
    kutu = db.relationship('Kutu')
    performed_by = db.relationship('Kullanici')


class CalibrationSchedule(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'calibration_schedule'

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('inventory_asset.id'), nullable=False, index=True)
    period_days = db.Column(db.Integer, nullable=False, default=180)
    warning_days = db.Column(db.Integer, nullable=False, default=15)
    provider = db.Column(db.String(150))
    certificate_template = db.Column(db.String(120))
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    note = db.Column(db.Text)


class CalibrationRecord(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'calibration_record'

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('inventory_asset.id'), nullable=False, index=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_order.id'), nullable=True, index=True)
    calibration_schedule_id = db.Column(db.Integer, db.ForeignKey('calibration_schedule.id'), nullable=True, index=True)
    calibration_date = db.Column(db.Date, nullable=False, index=True)
    next_calibration_date = db.Column(db.Date, index=True)
    calibrated_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    provider = db.Column(db.String(150))
    certificate_no = db.Column(db.String(120), index=True)
    certificate_file = db.Column(db.String(500))
    certificate_drive_file_id = db.Column(db.String(255))
    certificate_drive_folder_id = db.Column(db.String(255))
    certificate_mime_type = db.Column(db.String(120))
    certificate_size_bytes = db.Column(db.Integer)
    result_status = db.Column(db.String(30), default='passed', index=True)
    note = db.Column(db.Text)

    calibrated_by = db.relationship('Kullanici')
    work_order = db.relationship('WorkOrder')
    calibration_schedule = db.relationship('CalibrationSchedule')


class WorkOrderPartUsage(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'work_order_part_usage'

    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey('work_order.id'), nullable=False, index=True)
    spare_part_id = db.Column(db.Integer, db.ForeignKey('spare_part.id'), nullable=False, index=True)
    quantity_used = db.Column(db.Float, nullable=False, default=0)
    note = db.Column(db.Text)
    consumed_from_stock_id = db.Column(db.Integer, db.ForeignKey('spare_part_stock.id'), nullable=True, index=True)

    consumed_from_stock = db.relationship('SparePartStock')


class MeterDefinition(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'meter_definition'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    meter_type = db.Column(db.String(40), nullable=False, default='hours', index=True)
    unit = db.Column(db.String(20), nullable=False, default='h')
    description = db.Column(db.Text)
    equipment_template_id = db.Column(
        db.Integer,
        db.ForeignKey('equipment_template.id'),
        nullable=True,
        index=True
    )
    asset_id = db.Column(
        db.Integer,
        db.ForeignKey('inventory_asset.id'),
        nullable=True,
        index=True
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    equipment_template = db.relationship('EquipmentTemplate', backref='meter_definitions', lazy=True)
    readings = db.relationship('AssetMeterReading', backref='meter_definition', lazy=True, cascade='all, delete-orphan')
    trigger_rules = db.relationship('MaintenanceTriggerRule', backref='meter_definition', lazy=True)


class AssetMeterReading(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'asset_meter_reading'

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('inventory_asset.id'), nullable=False, index=True)
    meter_definition_id = db.Column(db.Integer, db.ForeignKey('meter_definition.id'), nullable=False, index=True)
    reading_value = db.Column(db.Float, nullable=False)
    reading_at = db.Column(db.DateTime, default=get_tr_now, nullable=False, index=True)
    note = db.Column(db.Text)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)

    recorded_by = db.relationship('Kullanici')


class MaintenanceTriggerRule(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'maintenance_trigger_rule'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    trigger_type = db.Column(db.String(40), nullable=False, default='days', index=True)
    equipment_template_id = db.Column(
        db.Integer,
        db.ForeignKey('equipment_template.id'),
        nullable=True,
        index=True
    )
    asset_id = db.Column(
        db.Integer,
        db.ForeignKey('inventory_asset.id'),
        nullable=True,
        index=True
    )
    meter_definition_id = db.Column(
        db.Integer,
        db.ForeignKey('meter_definition.id'),
        nullable=True,
        index=True
    )
    threshold_value = db.Column(db.Float, nullable=False, default=0)
    warning_lead_value = db.Column(db.Float, default=0)
    auto_create_work_order = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    last_trigger_reading = db.Column(db.Float)
    last_triggered_at = db.Column(db.DateTime)

    equipment_template = db.relationship('EquipmentTemplate', backref='maintenance_trigger_rules', lazy=True)


class AssignmentRecord(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'assignment_record'

    id = db.Column(db.Integer, primary_key=True)
    assignment_no = db.Column(db.String(40), nullable=False, unique=True, index=True)
    assignment_date = db.Column(db.Date, default=lambda: get_tr_now().date(), nullable=False, index=True)
    delivered_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    delivered_by_name = db.Column(db.String(160), nullable=True)
    airport_id = db.Column(db.Integer, db.ForeignKey('havalimani.id'), nullable=True, index=True)
    note = db.Column(db.Text)
    status = db.Column(db.String(20), default='active', nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    signed_document_key = db.Column(db.String(255))
    signed_document_url = db.Column(db.String(500))
    signed_document_name = db.Column(db.String(180))

    delivered_by = db.relationship('Kullanici', foreign_keys=[delivered_by_id], lazy=True)
    created_by = db.relationship('Kullanici', foreign_keys=[created_by_id], lazy=True)
    airport = db.relationship('Havalimani', backref='assignment_records', lazy=True)
    recipients = db.relationship(
        'AssignmentRecipient',
        backref='assignment',
        lazy=True,
        cascade='all, delete-orphan',
    )
    items = db.relationship(
        'AssignmentItem',
        backref='assignment',
        lazy=True,
        cascade='all, delete-orphan',
    )
    history_entries = db.relationship(
        'AssignmentHistoryEntry',
        backref='assignment',
        lazy=True,
        cascade='all, delete-orphan',
        order_by='AssignmentHistoryEntry.created_at.desc()',
    )

    @property
    def recipient_names(self):
        return ", ".join(
            recipient.user.tam_ad
            for recipient in self.recipients
            if recipient.user and not recipient.user.is_deleted
        )

    @property
    def active_item_count(self):
        return sum(1 for item in self.items if (item.remaining_quantity or 0) > 0)


class AssignmentRecipient(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'assignment_recipient'

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment_record.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=False, index=True)

    user = db.relationship('Kullanici', backref='assignment_recipients', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('assignment_id', 'user_id', name='uq_assignment_recipient'),
    )


class AssignmentItem(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'assignment_item'

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment_record.id'), nullable=False, index=True)
    material_id = db.Column(db.Integer, db.ForeignKey('malzeme.id'), nullable=True, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('inventory_asset.id'), nullable=True, index=True)
    item_name = db.Column(db.String(180), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=1)
    unit = db.Column(db.String(30), default='adet')
    note = db.Column(db.Text)
    returned_quantity = db.Column(db.Float, default=0)
    returned_at = db.Column(db.DateTime, nullable=True)
    returned_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    return_note = db.Column(db.Text)

    material = db.relationship('Malzeme', backref='assignment_items', lazy=True)
    asset = db.relationship('InventoryAsset', backref='assignment_items', lazy=True)
    returned_by = db.relationship('Kullanici', foreign_keys=[returned_by_id], lazy=True)

    @property
    def remaining_quantity(self):
        return max(float(self.quantity or 0) - float(self.returned_quantity or 0), 0)


class AssignmentHistoryEntry(db.Model, TimestampMixin):
    __tablename__ = 'assignment_history_entry'

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment_record.id'), nullable=False, index=True)
    event_type = db.Column(db.String(40), nullable=False, index=True)
    event_note = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)

    created_by = db.relationship('Kullanici', lazy=True)


class MaintenanceInstruction(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'maintenance_instruction'

    id = db.Column(db.Integer, primary_key=True)
    equipment_template_id = db.Column(db.Integer, db.ForeignKey('equipment_template.id'), nullable=False, unique=True, index=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text)
    manual_url = db.Column(db.String(500))
    visual_url = db.Column(db.String(500))
    revision_no = db.Column(db.String(40))
    revision_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    equipment_template = db.relationship(
        'EquipmentTemplate',
        backref=db.backref('maintenance_instruction', uselist=False, cascade='all, delete-orphan'),
        lazy=True,
    )


class PPERecord(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'ppe_record'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=False, index=True)
    airport_id = db.Column(db.Integer, db.ForeignKey('havalimani.id'), nullable=False, index=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment_record.id'), nullable=True, index=True)
    item_name = db.Column(db.String(160), nullable=False)
    brand_model = db.Column(db.String(160))
    size_info = db.Column(db.String(80))
    delivered_at = db.Column(db.Date, default=lambda: get_tr_now().date(), nullable=False, index=True)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    status = db.Column(db.String(30), default='aktif', nullable=False, index=True)
    description = db.Column(db.Text)
    photo_storage_key = db.Column(db.String(255))
    photo_url = db.Column(db.String(500))
    created_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)

    user = db.relationship('Kullanici', foreign_keys=[user_id], backref='ppe_records', lazy=True)
    airport = db.relationship('Havalimani', backref='ppe_records', lazy=True)
    assignment = db.relationship('AssignmentRecord', backref='ppe_records', lazy=True)
    created_by = db.relationship('Kullanici', foreign_keys=[created_by_id], lazy=True)
    events = db.relationship(
        'PPERecordEvent',
        backref='ppe_record',
        lazy=True,
        cascade='all, delete-orphan',
        order_by='PPERecordEvent.created_at.desc()',
    )


class PPERecordEvent(db.Model, TimestampMixin):
    __tablename__ = 'ppe_record_event'

    id = db.Column(db.Integer, primary_key=True)
    ppe_record_id = db.Column(db.Integer, db.ForeignKey('ppe_record.id'), nullable=False, index=True)
    event_type = db.Column(db.String(40), nullable=False, index=True)
    status_after = db.Column(db.String(30), nullable=False, index=True)
    event_note = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)

    created_by = db.relationship('Kullanici', lazy=True)

# --- CMS MODELLERİ ---

class SiteAyarlari(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    baslik = db.Column(db.String(200))
    alt_metin = db.Column(db.Text)
    iletisim_notu = db.Column(db.Text)

class Haber(db.Model, TimestampMixin):
    id = db.Column(db.Integer, primary_key=True)
    baslik = db.Column(db.String(200), nullable=False)
    icerik = db.Column(db.Text, nullable=False)
    tarih = db.Column(db.DateTime, default=get_tr_now, index=True)

class NavMenu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ad = db.Column(db.String(50), nullable=False)
    link = db.Column(db.String(200), default="#")
    sira = db.Column(db.Integer, default=0)

class SliderResim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    resim_url = db.Column(db.String(500), nullable=False)
    baslik = db.Column(db.String(200))
    alt_yazi = db.Column(db.Text)


# --- HOMEPAGE CONTENT MANAGEMENT MODELS ---

class HomeSlider(db.Model, TimestampMixin):
    __tablename__ = 'home_slider'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    subtitle = db.Column(db.String(250))
    description = db.Column(db.Text)
    image_url = db.Column(db.String(500))
    button_text = db.Column(db.String(80), default='Detaylı Bilgi')
    button_link = db.Column(db.String(300), default='#')
    order_index = db.Column(db.Integer, default=0, index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)

    @property
    def image_path(self):
        return self.image_url

    @image_path.setter
    def image_path(self, value):
        self.image_url = value


class HomeSection(db.Model, TimestampMixin):
    __tablename__ = 'home_section'

    id = db.Column(db.Integer, primary_key=True)
    section_key = db.Column(db.String(60), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    subtitle = db.Column(db.String(250))
    content = db.Column(db.Text)
    icon = db.Column(db.String(50))
    image_url = db.Column(db.String(500))
    order_index = db.Column(db.Integer, default=0, index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)

    @property
    def image_path(self):
        return self.image_url

    @image_path.setter
    def image_path(self, value):
        self.image_url = value


class Announcement(db.Model, TimestampMixin):
    __tablename__ = 'announcement'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), nullable=False, unique=True, index=True)
    summary = db.Column(db.Text)
    content = db.Column(db.Text, nullable=False)
    cover_image = db.Column(db.String(500))
    is_published = db.Column(db.Boolean, default=True, index=True)
    published_at = db.Column(db.DateTime, default=get_tr_now, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)

    author = db.relationship('Kullanici', backref='announcements')


class DocumentResource(db.Model, TimestampMixin):
    __tablename__ = 'document_resource'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text)
    file_path = db.Column(db.String(500))
    category = db.Column(db.String(100), index=True)
    order_index = db.Column(db.Integer, default=0, index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)


class TatbikatBelgesi(db.Model, TimestampMixin, SoftDeleteMixin):
    __tablename__ = 'tatbikat_belgesi'

    id = db.Column(db.Integer, primary_key=True)
    havalimani_id = db.Column(db.Integer, db.ForeignKey('havalimani.id'), nullable=False, index=True)
    yukleyen_kullanici_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=False, index=True)
    baslik = db.Column(db.String(180), nullable=False)
    tatbikat_tarihi = db.Column(db.Date, nullable=True, index=True)
    aciklama = db.Column(db.Text, nullable=True)
    dosya_adi = db.Column(db.String(255), nullable=False)
    drive_file_id = db.Column(db.String(255), nullable=False, unique=True, index=True)
    drive_folder_id = db.Column(db.String(255), nullable=False, index=True)
    mime_type = db.Column(db.String(120), nullable=False)
    dosya_boyutu = db.Column(db.BigInteger, nullable=False, default=0)

    yukleyen = db.relationship('Kullanici', backref='tatbikat_belgeleri', lazy=True)


class HomeStatCard(db.Model):
    __tablename__ = 'home_stat_card'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(140), nullable=False)
    value_text = db.Column(db.String(80), nullable=False)
    subtitle = db.Column(db.String(200))
    icon = db.Column(db.String(50))
    order_index = db.Column(db.Integer, default=0, index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)


class HomeQuickLink(db.Model):
    __tablename__ = 'home_quick_link'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(140), nullable=False)
    description = db.Column(db.String(260))
    link_url = db.Column(db.String(350), default='#')
    icon = db.Column(db.String(50))
    order_index = db.Column(db.Integer, default=0, index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)


class ContentWorkflow(db.Model, TimestampMixin):
    __tablename__ = 'content_workflow'

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(40), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='draft', index=True)
    published_at = db.Column(db.DateTime, nullable=True, index=True)
    published_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    last_edited_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    last_action = db.Column(db.String(40), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('entity_type', 'entity_id', name='uq_content_workflow_entity'),
    )

    published_by = db.relationship('Kullanici', foreign_keys=[published_by_id], lazy=True)
    last_edited_by = db.relationship('Kullanici', foreign_keys=[last_edited_by_id], lazy=True)


class ContentSEO(db.Model, TimestampMixin):
    __tablename__ = 'content_seo'

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(40), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=False, index=True)
    meta_title = db.Column(db.String(255), nullable=True)
    meta_description = db.Column(db.String(500), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('entity_type', 'entity_id', name='uq_content_seo_entity'),
    )


class MediaAsset(db.Model, TimestampMixin):
    __tablename__ = 'media_asset'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(60), nullable=False, index=True)
    alt_text = db.Column(db.String(255), nullable=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('kullanici.id'), nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    uploaded_by = db.relationship('Kullanici', backref='media_assets', lazy=True)
