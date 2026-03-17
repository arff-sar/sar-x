from flask import Blueprint, jsonify
from flask_login import login_required, current_user
from models import Malzeme

api_bp = Blueprint('api', __name__)

@api_bp.route('/api/envanter')
@login_required
def api_envanter():
    malzemeler = Malzeme.query.filter_by(havalimani_id=current_user.havalimani_id).all() if current_user.rol != 'sahip' else Malzeme.query.all()
    return jsonify({"durum": "basarili", "veri": [{"ad": m.ad, "sn": m.seri_no, "durum": m.durum} for m in malzemeler]})

@api_bp.route('/api/kutu/<string:kodu>')
@login_required
def api_kutu_detay(kodu):
    from models import Kutu
    kutu = Kutu.query.filter_by(kodu=kodu).first()
    if not kutu:
        return jsonify({"durum": "hata", "mesaj": "Kutu bulunamadi"}), 404
    
    malzemeler = [{"ad": m.ad, "durum": m.durum, "seri_no": m.seri_no} for m in kutu.malzemeler]
    
    return jsonify({
        "kutu_kodu": kutu.kodu,
        "havalimani": kutu.havalimani.ad,
        "malzemeler": malzemeler
    })