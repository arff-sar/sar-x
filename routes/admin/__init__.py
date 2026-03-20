from flask import Blueprint

# Blueprint'imizi oluşturuyoruz (Prefix eklemiyoruz ki eski URL yapınız bozulmasın)
admin_bp = Blueprint('admin', __name__)

# Alt modülleri dahil ediyoruz (Döngüsel hatayı önlemek için MUTLAKA en sonda olmalı)
from . import users, settings, logs, roles, approvals, notifications
from . import archive
