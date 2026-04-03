import json


def test_manifest_icon_assets_resolve(client):
    response = client.get("/manifest.json")

    assert response.status_code == 200
    payload = json.loads(response.data.decode("utf-8"))
    assert payload.get("start_url") == "/login"

    icon_sources = [item["src"] for item in payload.get("icons", [])]
    assert "/static/img/icon-192.png" in icon_sources
    assert "/static/img/icon-512.png" in icon_sources
    assert "/static/img/icon-maskable-512.png" in icon_sources

    for icon_path in icon_sources:
        icon_response = client.get(icon_path)
        assert icon_response.status_code == 200, icon_path
