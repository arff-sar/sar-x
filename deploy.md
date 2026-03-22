# SAR-X Production Deploy (Google Cloud Run)

## 1) Kök Problem
Önceki yaklaşımda production deploy komutu `gcloud run deploy ... --set-env-vars ... --set-secrets ...` ile parçalı çalışıyordu.
Bu yöntem:
- mevcut Cloud Run service konfigürasyonunu source of truth olarak repo içinde tutmuyor,
- hangi env/secrets’ın kalıcı olması gerektiğini deploy anındaki komuta bırakıyor,
- eksik bayrak veya eksik secret parametresi olduğunda yeni revision’da kritik değerlerin kaybolmasına yol açabiliyor.

Bu repo artık production için:
- **deklaratif Cloud Run service manifesti**
- **GitHub Actions tabanlı tekrar çalıştırılabilir deploy**
- **Secret Manager referanslı kritik env yönetimi**
kullanır.

## 2) Repo İçindeki Source of Truth
- Cloud Run service şablonu:
  - `.github/cloudrun/service.production.yaml.tmpl`
- Production deploy workflow:
  - `.github/workflows/deploy-production.yml`

Bu iki dosya production deploy’un tek doğruluk kaynağıdır.

## 3) GitHub Environment / Variables / Secrets
GitHub repository içinde `production` environment oluşturun.

### GitHub Environment Variables
Zorunlu:
- `GCP_PROJECT_ID`
- `GCP_REGION`
- `ARTIFACT_REGISTRY_REPOSITORY`
- `CLOUD_RUN_SERVICE`
- `CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT`
- `CLOUD_SQL_CONNECTION_NAME`
- `SECRET_KEY_SECRET_NAME`
- `DATABASE_URL_SECRET_NAME`
- `SMTP_PASSWORD_SECRET_NAME`
- `GCS_BUCKET_NAME`
- `PUBLIC_BASE_URL`
- `MAIL_USERNAME`
- `MAIL_FROM_EMAIL`

Opsiyonel ama önerilen:
- `GCS_PROJECT_ID`
- `GCS_UPLOAD_PREFIX`
- `GCS_PUBLIC_BASE_URL`
- `GCS_CACHE_CONTROL`
- `REDIS_URL`
- `MAIL_HOST`
- `MAIL_PORT`
- `MAIL_USE_TLS`
- `MAIL_REPLY_TO`
- `SESSION_COOKIE_SAMESITE`
- `CLOUD_RUN_MIN_INSTANCES`
- `CLOUD_RUN_MAX_INSTANCES`
- `CLOUD_RUN_CONCURRENCY`
- `CLOUD_RUN_TIMEOUT_SECONDS`
- `CLOUD_RUN_CPU`
- `CLOUD_RUN_MEMORY`

### GitHub Environment Secrets
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOYER_SERVICE_ACCOUNT`

## 4) Secret Manager
Kritik değerleri düz env olarak değil Secret Manager ile yönetin.

Zorunlu secret’lar:
- `SECRET_KEY_SECRET_NAME`
  İçerik: güçlü uygulama `SECRET_KEY`
- `DATABASE_URL_SECRET_NAME`
  İçerik: production PostgreSQL / Cloud SQL `DATABASE_URL`
- `SMTP_PASSWORD_SECRET_NAME`
  İçerik: SMTP parola değeri

Örnek:

```bash
printf '%s' 'VERY-LONG-RANDOM-SECRET-KEY' | gcloud secrets create sar-x-secret-key --data-file=-
printf '%s' 'postgresql+psycopg2://USER:PASSWORD@/DB?host=/cloudsql/PROJECT:REGION:INSTANCE' | gcloud secrets create sar-x-database-url --data-file=-
printf '%s' 'YOUR_SMTP_PASSWORD' | gcloud secrets create sar-x-smtp-password --data-file=-
```

Var olan secret için yeni versiyon eklemek isterseniz:

```bash
printf '%s' 'NEW-VALUE' | gcloud secrets versions add sar-x-secret-key --data-file=-
```

## 5) IAM Gereksinimleri
### GitHub deploy service account
`GCP_DEPLOYER_SERVICE_ACCOUNT` için en az:
- `roles/run.admin`
- `roles/iam.serviceAccountUser`
- `roles/cloudbuild.builds.editor`
- `roles/artifactregistry.writer`

### Cloud Run runtime service account
`CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT` için en az:
- `roles/secretmanager.secretAccessor`
- `roles/cloudsql.client`
- `roles/storage.objectAdmin` veya daha dar uygun storage rolü

Redis kullanılıyorsa ilgili ağ / erişim yetkileri ayrıca verilmelidir.

## 6) Workflow Akışı
Deploy workflow:
- `SAR-X CI` başarıyla tamamlandıktan sonra
- `main` branch push’larında otomatik tetiklenir
- isterse `workflow_dispatch` ile manuel de başlatılabilir

Akış sırası:
1. doğru commit checkout edilir
2. GitHub OIDC ile Google Cloud’a bağlanılır
3. image Cloud Build ile Artifact Registry’ye build edilir
4. Cloud Run service manifesti repo içindeki şablondan üretilir
5. `gcloud run services replace` ile service tam konfigürasyonla güncellenir
6. deploy sonrası env/secrets/cloudsql bağlantısı doğrulanır

## 7) Migration
Production’da `db.create_all()` kapalı kalmalıdır.
Deploy sonrası migration ayrı ve kontrollü çalıştırılmalıdır:

```bash
flask db upgrade
```

Bu adımı:
- ayrı GitHub Actions migration workflow’unda
- veya Cloud Run Job içinde
ayrı yürütün.

## 8) Scheduler Ayrımı
Web servis içinde scheduler kapalı kalmalıdır:
- `ENABLE_SCHEDULER=0`
- `ALLOW_CLOUD_RUN_WEB_SCHEDULER=0`

Günlük işler için Cloud Run Job + Cloud Scheduler kullanın.

## 9) Storage Notu
- Development için `STORAGE_BACKEND=local` kalabilir.
- Production için `STORAGE_BACKEND=gcs` kullanılmalıdır.
- `GCS_BUCKET_NAME` ve ilişkili değerler workflow manifestinde her deploy’da yeniden uygulanır.

## 10) Deploy Sonrası Doğrulama
Deploy tamamlandıktan sonra en az şunları kontrol edin:
- Cloud Run revision sağlıklı mı
- `/health` ve `/ready` dönüyor mu
- service config içinde `SECRET_KEY` ve `DATABASE_URL` secret env olarak bağlı mı
- `run.googleapis.com/cloudsql-instances` annotation doğru mu
- login sayfası açılıyor mu
- production veritabanı gerçekten doğru Cloud SQL instance’ına bağlı mı

## 11) Manuel Acil Durum Notu
Production ayarları artık elle `gcloud run services update --update-env-vars ...` ile taşınmamalıdır.
Kalıcı yöntem:
- Secret Manager secret değerini güncelle
- GitHub production variable/secrets’ı güncelle
- workflow’u yeniden çalıştır
