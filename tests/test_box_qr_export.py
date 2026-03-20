from extensions import db
from tests.factories import HavalimaniFactory, KutuFactory, KullaniciFactory, MalzemeFactory


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_box_qr_and_label_export_render_expected_content(client, app):
    with app.app_context():
        airport = HavalimaniFactory(ad="Erzurum Havalimanı", kodu="ERZ")
        user = KullaniciFactory(rol="depo_sorumlusu", havalimani=airport, is_deleted=False)
        box = KutuFactory(kodu="ERZ-KUTU-01", havalimani=airport)
        material = MalzemeFactory(ad="Gaz Ölçüm Cihazı", kutu=box, havalimani=airport, stok_miktari=2, is_deleted=False)
        db.session.add_all([airport, user, box, material])
        db.session.commit()
        user_id = user.id
        box_id = box.id
        box_code = box.kodu

    _login(client, user_id)
    qr_response = client.get(f"/qr-uret/kutu/{box_id}")
    label_response = client.get(f"/kutu/{box_code}/etiket")
    pdf_response = client.get(f"/kutu/{box_code}/etiket/pdf")

    label_html = label_response.data.decode("utf-8")

    assert qr_response.status_code == 200
    assert label_response.status_code == 200
    assert pdf_response.status_code == 200
    assert "ERZ-KUTU-01" in label_html
    assert "ERZURUM HAVALİMANI" in label_html
    assert "Gaz Ölçüm Cihazı" in label_html
    assert pdf_response.mimetype == "application/pdf"
