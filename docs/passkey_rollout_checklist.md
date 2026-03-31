# Passkey Rollout Checklist

Bu not, `PASSKEY_ENABLED` kapalı varsayılanını koruyarak kontrollü üretim açılışı için son doğrulama listesidir.

## Gerekli config

- `PASSKEY_ENABLED=false` varsayılan kalmalıdır.
- Kontrollü açılışta ayrıca şu değerler zorunludur:
  - `PASSKEY_RP_ID`
  - `PASSKEY_ORIGIN` veya `PASSKEY_ALLOWED_ORIGINS`
- Production origin değerleri `https://` olmalıdır.
- Origin host değeri `PASSKEY_RP_ID` ile aynı olmalı veya onun alt alan adı olmalıdır.
- Production ortamında güçlü `SECRET_KEY` ve Redis tabanlı rate-limit storage korunmalıdır.

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
