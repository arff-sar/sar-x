from flask import url_for


def build_asset_qr_url(asset):
    if not asset:
        return ""
    return url_for("inventory.quick_asset_view", asset_id=asset.id, _external=True)


def assign_asset_qr(asset, *, force=False):
    if not asset:
        return ""
    if force or not (asset.qr_code or "").strip():
        asset.qr_code = build_asset_qr_url(asset)
    return asset.qr_code or ""

