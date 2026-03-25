def generate_inventory_code(asset):
    """Canonical envanter kodu: mevcut sistem standardını korur."""
    if not asset:
        return None
    return asset.asset_code

