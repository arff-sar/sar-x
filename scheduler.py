import atexit
import logging
import os
from datetime import timedelta
from typing import Optional

from sqlalchemy import and_

from extensions import db
from models import AssetMeterReading, InventoryAsset, MaintenanceTriggerRule, get_tr_now

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except Exception:  # pragma: no cover - optional dependency
    BackgroundScheduler = None

try:
    import fcntl
except Exception:  # pragma: no cover - non-posix fallback
    fcntl = None


LOGGER = logging.getLogger("sarx.scheduler")
_scheduler = None
_lock_file = None


def _running_in_cloud_run_web_service():
    return (
        bool(os.getenv("K_SERVICE"))
        and not bool(os.getenv("CLOUD_RUN_JOB"))
        and not bool(os.getenv("CLOUD_RUN_EXECUTION"))
    )


def _is_primary_process(app):
    if app.config.get("TESTING"):
        return False
    if app.debug and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return False
    return True


def _acquire_process_lock(lock_path="/tmp/sarx_scheduler.lock"):
    if fcntl is None:
        return None
    try:
        handle = open(lock_path, "w")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write(str(os.getpid()))
        handle.flush()
        return handle
    except Exception:
        return None


def _release_process_lock():
    global _lock_file
    if not _lock_file:
        return
    try:
        if fcntl is not None:
            fcntl.flock(_lock_file.fileno(), fcntl.LOCK_UN)
    except Exception:
        LOGGER.exception("Scheduler lock serbest bırakılamadı.")
    finally:
        try:
            _lock_file.close()
        except Exception:
            pass
        _lock_file = None


def _daily_maintenance_check(app):
    with app.app_context():
        try:
            today = get_tr_now().date()
            soon_date = today + timedelta(days=7)

            overdue_query = InventoryAsset.query.filter(
                and_(
                    InventoryAsset.is_deleted.is_(False),
                    InventoryAsset.status != "pasif",
                    InventoryAsset.next_maintenance_date.isnot(None),
                    InventoryAsset.next_maintenance_date < today,
                )
            )
            upcoming_query = InventoryAsset.query.filter(
                and_(
                    InventoryAsset.is_deleted.is_(False),
                    InventoryAsset.status != "pasif",
                    InventoryAsset.next_maintenance_date.isnot(None),
                    InventoryAsset.next_maintenance_date >= today,
                    InventoryAsset.next_maintenance_date <= soon_date,
                )
            )

            overdue_assets = overdue_query.all()
            upcoming_assets = upcoming_query.all()

            changed = False
            for asset in overdue_assets:
                if asset.maintenance_state not in {"gecikmis", "bakimda"}:
                    asset.maintenance_state = "gecikmis"
                    changed = True

            for asset in upcoming_assets:
                if asset.maintenance_state in {"normal", "", None}:
                    asset.maintenance_state = "yaklasan"
                    changed = True

            meter_warning_count = 0
            meter_rules = MaintenanceTriggerRule.query.filter(
                MaintenanceTriggerRule.is_deleted.is_(False),
                MaintenanceTriggerRule.is_active.is_(True),
                MaintenanceTriggerRule.meter_definition_id.isnot(None),
            ).all()
            for rule in meter_rules:
                if not rule.asset_id:
                    continue
                asset = InventoryAsset.query.filter_by(id=rule.asset_id, is_deleted=False).first()
                if not asset or asset.status == "pasif":
                    continue
                latest = AssetMeterReading.query.filter_by(
                    asset_id=asset.id,
                    meter_definition_id=rule.meter_definition_id,
                    is_deleted=False,
                ).order_by(AssetMeterReading.reading_at.desc()).first()
                if not latest:
                    continue
                threshold = float(rule.threshold_value or 0)
                warning = float(rule.warning_lead_value or 0)
                if threshold <= 0:
                    continue
                if latest.reading_value >= max(threshold - warning, 0):
                    meter_warning_count += 1
                    if asset.maintenance_state in {"normal", "", None}:
                        asset.maintenance_state = "yaklasan"
                        changed = True

            if changed:
                db.session.commit()

            summary = {
                "overdue_count": len(overdue_assets),
                "upcoming_count": len(upcoming_assets),
                "meter_warning_count": meter_warning_count,
                "updated": changed,
            }
            LOGGER.info(
                "Bakım kontrolü tamamlandı | geciken=%s | yaklasan=%s | sayac_yaklasan=%s | guncellenen=%s",
                len(overdue_assets),
                len(upcoming_assets),
                meter_warning_count,
                "evet" if changed else "hayir",
            )
            return summary
        except Exception:
            db.session.rollback()
            LOGGER.exception("Bakım kontrol job'ı hata ile sonuçlandı.")
            raise


def run_daily_maintenance_job(app):
    """
    Cloud Run Jobs / manuel tetikleme için günlük bakım kontrolünü tek seferlik çalıştırır.
    """
    return _daily_maintenance_check(app)


def shutdown_scheduler():
    global _scheduler
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
            LOGGER.info("Scheduler durduruldu.")
        except Exception:
            LOGGER.exception("Scheduler kapatılırken hata oluştu.")
        finally:
            _scheduler = None
    _release_process_lock()


def start_scheduler(app):
    global _scheduler
    global _lock_file

    if not app.config.get("ENABLE_SCHEDULER", True):
        app.logger.info("Scheduler kapalı (ENABLE_SCHEDULER=False).")
        return None

    if _running_in_cloud_run_web_service() and not app.config.get("ALLOW_CLOUD_RUN_WEB_SCHEDULER", False):
        app.logger.warning(
            "Cloud Run web service ortamında scheduler başlatılmadı. "
            "Zamanlı işler için Cloud Run Job / Cloud Scheduler kullanılmalıdır."
        )
        return None

    if not _is_primary_process(app):
        app.logger.info("Scheduler bu süreçte başlatılmadı (primary process değil).")
        return None

    if BackgroundScheduler is None:
        app.logger.warning("APScheduler bulunamadı, scheduler başlatılmadı.")
        return None

    if _scheduler:
        app.logger.info("Scheduler zaten aktif.")
        return _scheduler

    lock_file = _acquire_process_lock()
    if fcntl is not None and lock_file is None:
        app.logger.warning("Başka bir süreç scheduler lock'unu tuttuğu için scheduler atlandı.")
        return None
    _lock_file = lock_file

    _scheduler = BackgroundScheduler(timezone="Europe/Istanbul")
    _scheduler.add_job(
        func=lambda: _daily_maintenance_check(app),
        trigger="interval",
        hours=24,
        id="daily-maintenance-check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    try:
        _scheduler.start()
        app.logger.info("Scheduler başlatıldı.")
        _daily_maintenance_check(app)
        atexit.register(shutdown_scheduler)
    except Exception:
        app.logger.exception("Scheduler başlatılamadı.")
        shutdown_scheduler()
        return None

    return _scheduler
