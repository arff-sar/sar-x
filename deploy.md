# SAR-X Production Deploy (Google Cloud Run)

## 1) Ön Koşullar
- GCP projesi oluşturulmuş olmalı.
- Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud SQL API, Cloud Storage API açık olmalı.
- PostgreSQL için Cloud SQL instance hazır olmalı.
- Medya dosyaları için bir Cloud Storage bucket hazır olmalı.

## 2) Secret ve Env Hazırlığı
Örnek secret yükleme:

```bash
printf '%s' 'YOUR_SMTP_PASSWORD' | gcloud secrets create mail-smtp-password --data-file=-
```

Uygulama için kritik env:
- `APP_ENV=production`
- `SECRET_KEY=<strong-random>`
- `DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@/DB_NAME?host=/cloudsql/PROJECT:REGION:INSTANCE`
- `MAIL_FROM_EMAIL=...`
- `MAIL_USERNAME=...`
- `MAIL_SECRET_PROJECT_ID=<gcp-project-id>`
- `MAIL_PASSWORD_SECRET_NAME=mail-smtp-password`
- `ENABLE_SCHEDULER=0`
- `REDIS_URL=<opsiyonel memorystore/redis>`
- `STORAGE_BACKEND=gcs`
- `GCS_BUCKET_NAME=<bucket-name>`
- `GCS_PUBLIC_BASE_URL=https://storage.googleapis.com/<bucket-name>`
- `GCS_UPLOAD_PREFIX=uploads`
- `ALLOW_CLOUD_RUN_WEB_SCHEDULER=0`

## 3) Container Build ve Deploy

```bash
gcloud builds submit --tag REGION-docker.pkg.dev/PROJECT/REPO/sarx:latest

gcloud run deploy sarx-web \
  --image REGION-docker.pkg.dev/PROJECT/REPO/sarx:latest \
  --platform managed \
  --region REGION \
  --allow-unauthenticated \
  --port 8080 \
  --set-env-vars APP_ENV=production,ENABLE_SCHEDULER=0,ALLOW_CLOUD_RUN_WEB_SCHEDULER=0,STORAGE_BACKEND=gcs,GCS_BUCKET_NAME=YOUR_BUCKET,GCS_PUBLIC_BASE_URL=https://storage.googleapis.com/YOUR_BUCKET \
  --set-secrets SECRET_KEY=projects/PROJECT/secrets/app-secret-key:latest
```

Cloud SQL kullanıyorsanız deploy komutuna:
- `--add-cloudsql-instances PROJECT:REGION:INSTANCE`

Cloud Storage kullanıyorsanız servis hesabına bucket yetkisi verin:
- `roles/storage.objectAdmin` veya daha kısıtlı object write/read rolü

Rate limit'i instance'lar arasında paylaşmak istiyorsanız:
- `REDIS_URL=redis://HOST:PORT/0`

## 4) DB Migration
Production’da `db.create_all()` kapalıdır. Migration çalıştırın:

```bash
flask db upgrade
```

Bunu Cloud Run Job ya da ayrı migration pipeline adımı ile tetikleyin.

## 5) Scheduler Ayrımı
Web serviste scheduler kapalı önerilir (`ENABLE_SCHEDULER=0`).
Günlük bakım job’ı için:

```bash
python -m jobs daily-maintenance
```

Bu komut Cloud Run Job + Cloud Scheduler ile düzenli tetiklenebilir.

## 6) Storage Notu
- `STORAGE_BACKEND=local` development için kalabilir.
- Production/Cloud Run için medya yüklemelerinde `STORAGE_BACKEND=gcs` kullanılmalıdır.
- Mevcut upload route'ları korunur; sadece backend adapter değişir.
