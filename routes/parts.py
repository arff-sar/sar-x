from flask import Blueprint, flash, redirect, url_for
from flask_login import current_user, login_required

from decorators import has_permission, permission_required
from extensions import table_exists
from models import AssetSparePartLink, InventoryAsset, SparePart


parts_bp = Blueprint("parts", __name__)


def _can_view_all_scope():
    return has_permission("settings.manage") or has_permission("logs.view")


def _linked_asset_for_part(part_id):
    if not table_exists("asset_spare_part_link"):
        return None

    query = (
        InventoryAsset.query.join(
            AssetSparePartLink,
            AssetSparePartLink.asset_id == InventoryAsset.id,
        )
        .filter(
            AssetSparePartLink.spare_part_id == part_id,
            AssetSparePartLink.is_deleted.is_(False),
            AssetSparePartLink.is_active.is_(True),
            InventoryAsset.is_deleted.is_(False),
        )
        .order_by(InventoryAsset.updated_at.desc(), InventoryAsset.id.desc())
    )
    if not _can_view_all_scope():
        query = query.filter(InventoryAsset.havalimani_id == current_user.havalimani_id)
    return query.first()


def _redirect_inventory_notice(category="info"):
    flash(
        "Yedek parça yönetimi artık malzeme/ekipman detayı içinden yürütülüyor.",
        category,
    )
    return redirect(url_for("inventory.envanter"))


@parts_bp.route("/yedek-parcalar")
@login_required
@permission_required("parts.view")
def spare_parts_list():
    return _redirect_inventory_notice()


@parts_bp.route("/yedek-parcalar/yeni", methods=["GET", "POST"])
@login_required
@permission_required("parts.edit")
def spare_part_create():
    return _redirect_inventory_notice()


@parts_bp.route("/yedek-parcalar/<int:part_id>", methods=["GET", "POST"])
@login_required
@permission_required("parts.view")
def spare_part_detail(part_id):
    part = SparePart.query.filter_by(id=part_id, is_deleted=False).first_or_404()
    linked_asset = _linked_asset_for_part(part.id)
    if linked_asset:
        flash(
            f"{part.part_code} parçası için bağlı ekipman detayına yönlendirildiniz.",
            "info",
        )
        return redirect(url_for("inventory.asset_detail", asset_id=linked_asset.id))
    return _redirect_inventory_notice()
