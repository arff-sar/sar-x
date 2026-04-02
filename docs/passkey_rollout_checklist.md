# Passkey Rollout Checklist

Bu not, `PASSKEY_ENABLED` kapalı varsayılanını koruyarak kontrollü üretim açılışı için son doğrulama listesidir.

## Gerekli config

- `PASSKEY_ENABLED=false` varsayılan kalmalıdır.
- Kontrollü açılışta ayrıca şu değerler zorunludur:
  - `PASSKEY_RP_ID`
  - `PASSKEY_ORIGIN` veya `PASSKEY_ALLOWED_ORIGINS`
- Production origin değerleri `https://` olmalıdır.
- Origin host değeri `PASSKEY_RP_ID` ile aynı olmalı veya onun alt alan adı olmalıdır.
- Production ortamında güçlü `SECRET_KEY` ve uygun rate-limit storage ayarı (`RATELIMIT_STORAGE_URI`, varsayılan `memory://`) korunmalıdır.

## Staging / Development minimum env seti

Staging veya development doğrulaması için önerilen minimum anahtarlar:

- `PASSKEY_ENABLED=true`
- `PASSKEY_RP_ID=<ortam hostu>` (örn: `staging.sarx.org`, local için `localhost`)
- `PASSKEY_ORIGIN=https://<ortam hostu>` (local için `http://localhost:<port>`)
- (Opsiyonel) `PASSKEY_ALLOWED_ORIGINS=<virgülle birden fazla origin>`
- `PASSKEY_CHALLENGE_TTL_SECONDS=180` (önerilen varsayılan)

Notlar:

- `PASSKEY_ORIGIN` ve `PASSKEY_ALLOWED_ORIGINS` birlikte verilebilir; her origin hostu `PASSKEY_RP_ID` ile uyumlu olmalıdır.
- Development/Testing ortamında eksik `PASSKEY_RP_ID` veya origin varsa uygulama host fallback kullanır; staging doğrulamasında explicit değer kullanın.

## Startup fail koşulları (fail-closed)

`PASSKEY_ENABLED=true` iken:

1. Production ortamında `PASSKEY_RP_ID` boşsa uygulama startup sırasında hata verir.
2. Production ortamında `PASSKEY_ORIGIN` / `PASSKEY_ALLOWED_ORIGINS` boşsa startup hata verir.
3. Origin şeması `https` değilse (local host istisnası hariç) startup hata verir.
4. Origin hostu `PASSKEY_RP_ID` ile eşleşmiyorsa veya alt alanı değilse startup hata verir.

## Gerçek cihaz smoke checklist

1. `PASSKEY_ENABLED=false` ile `/login` aç:
   - Klasik e-posta/sifre/captcha ekranı aynen görünmeli.
   - Passkey tetikleyicisi görünmemeli.
2. `PASSKEY_ENABLED=true` ile destekli mobil cihazda `/login` aç:
   - Masaüstü görünümü bozulmamalı.
   - Mobilde passkey tetikleyicisi yalnız destek varsa görünmeli.
3. Login ekranında captcha doldurmadan passkey dene:
   - İstek güvenli biçimde reddedilmeli.
4. Passkey prompt'unu kullanıcı iptal etsin:
   - Sayfa bozulmadan klasik login formu kullanılabilir kalmalı.
5. Authenticated bir kullanıcı ile passkey kaydı yap:
   - Kayıt başarı mesajı dönmeli.
6. Aynı cihazda passkey login yap:
   - Başarılı giriş sonrası doğru dashboard'a yönlenmeli.
7. Hatalı captcha ile passkey login dene:
   - Giriş kurulmamalı.
8. Login sonrası `logout` yap:
   - Oturum kapanmalı, korumalı sayfalar tekrar `/login`e dönmeli.
9. PWA kurulu cihazda tekrar dene:
   - `sw.js` / manifest davranışı auth akışını bozmamalı.
10. Desteklemeyen cihaz/tarayıcıda test et:
   - Passkey akışı sessiz fallback vermeli, klasik login çalışmalı.

## Açılış sırası

1. Önce staging veya smoke ortamında `PASSKEY_ENABLED=true`.
2. Sadece dar kullanıcı grubu ile gerçek cihaz smoke testi.
3. Hata/log izlemesi temizse üretimde kontrollü açılış.
4. Sorunda yalnız feature flag kapatılarak legacy moda dön.
