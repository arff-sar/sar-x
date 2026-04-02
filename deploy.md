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
- `SECRET_KEY_SECRET_VERSION`
- `DATABASE_URL_SECRET_VERSION`
- `SMTP_PASSWORD_SECRET_VERSION`
- `DATABASE_URL_EXPECTED_USERNAME`
- `DATABASE_URL_EXPECTED_DB_NAME`
- `GCS_BUCKET_NAME`
- `PUBLIC_BASE_URL`
- `MAIL_USERNAME`
- `MAIL_FROM_EMAIL`
- `RATELIMIT_STORAGE_URI` (production’da `memory://` olamaz; merkezi backend olmalıdır, örn: `redis://...`)

Opsiyonel ama önerilen:
- `GCS_PROJECT_ID`
- `GCS_UPLOAD_PREFIX`
- `GCS_PUBLIC_BASE_URL`
- `GCS_CACHE_CONTROL`
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
- `MIGRATION_JOB_NAME` (varsayılan: `${CLOUD_RUN_SERVICE}-db-migrate`)

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
  Format: `postgresql+psycopg2://USER:PASSWORD@/DB?host=/cloudsql/PROJECT:REGION:INSTANCE`
- `SMTP_PASSWORD_SECRET_NAME`
  İçerik: SMTP parola değeri

`*_SECRET_VERSION` değişkenleri için açık sürüm numarası kullanın (örn: `3`, `12`, `7`).

İdempotent secret yönetimi örneği:

```bash
GCP_PROJECT_ID="YOUR_PROJECT_ID"

upsert_secret() {
  local secret_name="$1"
  local payload="$2"
  if gcloud secrets describe "${secret_name}" --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
    printf '%s' "${payload}" | gcloud secrets versions add "${secret_name}" --project "${GCP_PROJECT_ID}" --data-file=-
  else
    printf '%s' "${payload}" | gcloud secrets create "${secret_name}" --project "${GCP_PROJECT_ID}" --replication-policy="automatic" --data-file=-
  fi
}

upsert_secret "sar-x-secret-key" "VERY-LONG-RANDOM-SECRET-KEY"
upsert_secret "sar-x-database-url" "postgresql+psycopg2://USER:PASSWORD@/DB?host=/cloudsql/PROJECT:REGION:INSTANCE"
upsert_secret "sar-x-smtp-password" "YOUR_SMTP_PASSWORD"
```

Sürüm numaralarını okuyup GitHub `production` environment variable’larına yazın:

```bash
SECRET_KEY_SECRET_VERSION="$(gcloud secrets versions list sar-x-secret-key --project "${GCP_PROJECT_ID}" --sort-by='~name' --limit=1 --format='value(name)')"
DATABASE_URL_SECRET_VERSION="$(gcloud secrets versions list sar-x-database-url --project "${GCP_PROJECT_ID}" --sort-by='~name' --limit=1 --format='value(name)')"
SMTP_PASSWORD_SECRET_VERSION="$(gcloud secrets versions list sar-x-smtp-password --project "${GCP_PROJECT_ID}" --sort-by='~name' --limit=1 --format='value(name)')"

gh variable set SECRET_KEY_SECRET_VERSION --repo arff-sar/sar-x --env production --body "${SECRET_KEY_SECRET_VERSION}"
gh variable set DATABASE_URL_SECRET_VERSION --repo arff-sar/sar-x --env production --body "${DATABASE_URL_SECRET_VERSION}"
gh variable set SMTP_PASSWORD_SECRET_VERSION --repo arff-sar/sar-x --env production --body "${SMTP_PASSWORD_SECRET_VERSION}"
```

## 5) IAM Gereksinimleri
### GitHub deploy service account
`GCP_DEPLOYER_SERVICE_ACCOUNT` için en az:
- `roles/run.admin`
- `roles/iam.serviceAccountUser`
- `roles/cloudbuild.builds.editor`
- `roles/artifactregistry.writer`
- `roles/logging.viewer`

### Cloud Run runtime service account
`CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT` için en az:
- `roles/secretmanager.secretAccessor`
- `roles/cloudsql.client`
- `roles/storage.objectAdmin` veya daha dar uygun storage rolü

Rate-limit backend olarak Redis/Memorystore kullanılıyorsa ilgili ağ (VPC connector vb.) ve erişim yetkileri ayrıca doğrulanmalıdır.

## 6) Workflow Akışı
Deploy workflow:
- `SAR-X CI` başarıyla tamamlandıktan sonra
- `main` branch push’larında otomatik tetiklenir
- isterse `workflow_dispatch` ile manuel de başlatılabilir

Akış sırası:
1. doğru commit checkout edilir
2. GitHub OIDC ile Google Cloud’a bağlanılır
3. Secret Manager payload’ları (SECRET_KEY, DATABASE_URL, SMTP_PASSWORD) erişilebilirlik ve format açısından doğrulanır
   - boş payload kontrolü
   - `DATABASE_URL` için beklenen kullanıcı, beklenen db adı, unix socket host ve placeholder kontrolü
4. `RATELIMIT_STORAGE_URI` değeri doğrulanır (`memory://` kabul edilmez)
5. image Cloud Build ile Artifact Registry’ye build edilir
6. build edilen image ile Cloud Run Job üzerinden migration (`flask --app app:create_app db upgrade`) çalıştırılır
7. Cloud Run service manifesti repo içindeki şablondan üretilir
8. `gcloud run services replace` ile service tam konfigürasyonla güncellenir
9. deploy sonrası env/secrets/cloudsql bağlantısı ve secret ad+sürüm eşleşmesi doğrulanır
10. aktif revision `Ready=True` doğrulanır
11. runtime `/health`, `/ready` ve `/login` endpoint’leri doğrulanır
12. `/login` için challenge token rotasyonu smoke-check yapılır (ardışık iki GET isteğinde token farklı olmalı)
13. yalnızca deploy edilen revision loglarında kritik kalıplar taranır (`Güçlü bir SECRET_KEY zorunludur`, `Worker failed to boot`, `password authentication failed`, `OperationalError`, `RuntimeError`)

## 7) Migration
Production’da `db.create_all()` kapalı kalmalıdır.
Deploy workflow migration adımını **pre-deploy Cloud Run Job** olarak çalıştırır.

Varsayılan job adı:
- `${CLOUD_RUN_SERVICE}-db-migrate`

İsteğe bağlı override:
- `MIGRATION_JOB_NAME` (GitHub production variable)

Migration komutu workflow içinde:
- `flask --app app:create_app db upgrade`

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
- Cloud Run revision `Ready=True` mi
- `/health` ve `/ready` 200 dönüyor mu
- `/login` 200 veya 302 dönüyor mu
- `/login` ardışık iki GET çağrısında captcha token değişiyor mu
- service config içinde `SECRET_KEY` ve `DATABASE_URL` secret env olarak bağlı mı
- service config içinde `SECRET_KEY`/`DATABASE_URL`/`SMTP_PASSWORD` secret ad+sürüm eşleşmesi doğru mu
- `run.googleapis.com/cloudsql-instances` annotation doğru mu
- yalnızca aktif revision loglarında `Güçlü bir SECRET_KEY zorunludur`, `Worker failed to boot`, `password authentication failed`, `OperationalError`, `RuntimeError` kalıpları geçiyor mu
- login sayfası açılıyor mu
- production veritabanı gerçekten doğru Cloud SQL instance’ına bağlı mı

## 11) Manuel Acil Durum Notu
Production ayarları artık elle `gcloud run services update --update-env-vars ...` ile taşınmamalıdır.
Kalıcı yöntem:
- Secret Manager secret değerini güncelle
- Gerekirse ilgili `*_SECRET_VERSION` değişkenini hedef sürüme güncelle
- `DATABASE_URL_EXPECTED_USERNAME` ve `DATABASE_URL_EXPECTED_DB_NAME` değerlerini gerçek üretim bilgileriyle tutarlı tut
- GitHub production variable/secrets’ı güncelle
- workflow’u yeniden çalıştır

## 12) Tekrar Çalıştırılabilir Operasyon Akışı (Örnek)
```bash
set -euo pipefail

GCP_PROJECT_ID="YOUR_PROJECT_ID"
GCP_REGION="YOUR_REGION"
CLOUD_RUN_SERVICE="YOUR_SERVICE_NAME"

SECRET_KEY_SECRET_NAME="sar-x-secret-key"
DATABASE_URL_SECRET_NAME="sar-x-database-url"
SMTP_PASSWORD_SECRET_NAME="sar-x-smtp-password"

SECRET_KEY_VALUE="VERY_LONG_RANDOM_SECRET_KEY"
DATABASE_URL_VALUE="postgresql+psycopg2://EXPECTED_DB_USER:STRONG_DB_PASSWORD@/EXPECTED_DB_NAME?host=/cloudsql/YOUR_PROJECT_ID:YOUR_REGION:YOUR_INSTANCE"
SMTP_PASSWORD_VALUE="YOUR_SMTP_PASSWORD"

upsert_secret() {
  local secret_name="$1"
  local payload="$2"
  if gcloud secrets describe "${secret_name}" --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
    printf '%s' "${payload}" | gcloud secrets versions add "${secret_name}" --project "${GCP_PROJECT_ID}" --data-file=-
  else
    printf '%s' "${payload}" | gcloud secrets create "${secret_name}" --project "${GCP_PROJECT_ID}" --replication-policy="automatic" --data-file=-
  fi
}

upsert_secret "${SECRET_KEY_SECRET_NAME}" "${SECRET_KEY_VALUE}"
upsert_secret "${DATABASE_URL_SECRET_NAME}" "${DATABASE_URL_VALUE}"
upsert_secret "${SMTP_PASSWORD_SECRET_NAME}" "${SMTP_PASSWORD_VALUE}"

SECRET_KEY_SECRET_VERSION="$(gcloud secrets versions list "${SECRET_KEY_SECRET_NAME}" --project "${GCP_PROJECT_ID}" --sort-by='~name' --limit=1 --format='value(name)')"
DATABASE_URL_SECRET_VERSION="$(gcloud secrets versions list "${DATABASE_URL_SECRET_NAME}" --project "${GCP_PROJECT_ID}" --sort-by='~name' --limit=1 --format='value(name)')"
SMTP_PASSWORD_SECRET_VERSION="$(gcloud secrets versions list "${SMTP_PASSWORD_SECRET_NAME}" --project "${GCP_PROJECT_ID}" --sort-by='~name' --limit=1 --format='value(name)')"

gh variable set SECRET_KEY_SECRET_NAME --repo arff-sar/sar-x --env production --body "${SECRET_KEY_SECRET_NAME}"
gh variable set DATABASE_URL_SECRET_NAME --repo arff-sar/sar-x --env production --body "${DATABASE_URL_SECRET_NAME}"
gh variable set SMTP_PASSWORD_SECRET_NAME --repo arff-sar/sar-x --env production --body "${SMTP_PASSWORD_SECRET_NAME}"

gh variable set SECRET_KEY_SECRET_VERSION --repo arff-sar/sar-x --env production --body "${SECRET_KEY_SECRET_VERSION}"
gh variable set DATABASE_URL_SECRET_VERSION --repo arff-sar/sar-x --env production --body "${DATABASE_URL_SECRET_VERSION}"
gh variable set SMTP_PASSWORD_SECRET_VERSION --repo arff-sar/sar-x --env production --body "${SMTP_PASSWORD_SECRET_VERSION}"

gh variable set DATABASE_URL_EXPECTED_USERNAME --repo arff-sar/sar-x --env production --body "EXPECTED_DB_USER"
gh variable set DATABASE_URL_EXPECTED_DB_NAME --repo arff-sar/sar-x --env production --body "EXPECTED_DB_NAME"

gh workflow run "SAR-X Production Deploy" --repo arff-sar/sar-x --ref main

SERVICE_URL="$(gcloud run services describe "${CLOUD_RUN_SERVICE}" --region "${GCP_REGION}" --project "${GCP_PROJECT_ID}" --format='value(status.url)')"
READY_STATUS="$(gcloud run services describe "${CLOUD_RUN_SERVICE}" --region "${GCP_REGION}" --project "${GCP_PROJECT_ID}" --format='value(status.conditions[?type=Ready].status)')"
REVISION_NAME="$(gcloud run services describe "${CLOUD_RUN_SERVICE}" --region "${GCP_REGION}" --project "${GCP_PROJECT_ID}" --format='value(status.latestReadyRevisionName)')"
[ -n "${REVISION_NAME}" ] || REVISION_NAME="$(gcloud run services describe "${CLOUD_RUN_SERVICE}" --region "${GCP_REGION}" --project "${GCP_PROJECT_ID}" --format='value(status.latestCreatedRevisionName)')"
[ "${READY_STATUS}" = "True" ]
[ -n "${REVISION_NAME}" ]

curl -sS -o /tmp/sarx-health-body.txt -w "%{http_code}" "${SERVICE_URL}/health" | grep -x "200"
curl -sS -o /tmp/sarx-ready-body.txt -w "%{http_code}" "${SERVICE_URL}/ready" | grep -x "200"
curl -sS -o /tmp/sarx-login-body.txt -w "%{http_code}" "${SERVICE_URL}/login" | grep -E "^(200|302)$"

COOKIE_JAR="$(mktemp)"
curl -L -sS -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" -o /tmp/sarx-login-1.html "${SERVICE_URL}/login" >/dev/null
curl -L -sS -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" -o /tmp/sarx-login-2.html "${SERVICE_URL}/login" >/dev/null
TOKEN_ONE="$(python - <<'PY'
import re
text=open('/tmp/sarx-login-1.html','r',encoding='utf-8',errors='ignore').read()
m=re.search(r'data-captcha-token="([^"]+)"', text)
print(m.group(1) if m else "")
PY
)"
TOKEN_TWO="$(python - <<'PY'
import re
text=open('/tmp/sarx-login-2.html','r',encoding='utf-8',errors='ignore').read()
m=re.search(r'data-captcha-token="([^"]+)"', text)
print(m.group(1) if m else "")
PY
)"
[ -n "${TOKEN_ONE}" ]
[ -n "${TOKEN_TWO}" ]
[ "${TOKEN_ONE}" != "${TOKEN_TWO}" ]

START_TIME="$(date -u -d '20 minutes ago' +%Y-%m-%dT%H:%M:%SZ)"
LOG_OUTPUT="$(mktemp)"
gcloud logging read "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${CLOUD_RUN_SERVICE}\" AND resource.labels.location=\"${GCP_REGION}\" AND resource.labels.revision_name=\"${REVISION_NAME}\" AND timestamp>=\"${START_TIME}\"" --project "${GCP_PROJECT_ID}" --limit=300 --format='value(textPayload, jsonPayload.message)' > "${LOG_OUTPUT}"
if grep -Ein "Güçlü bir SECRET_KEY zorunludur|Worker failed to boot|password authentication failed|OperationalError|RuntimeError" "${LOG_OUTPUT}"; then
  echo "Kritik log kalıbı bulundu, deploy doğrulaması başarısız."
  exit 1
fi
```
