// 1. Dış Kütüphaneler HER ZAMAN en üstte tanımlanmalıdır
importScripts('https://cdn.jsdelivr.net/npm/idb@7/build/umd.js');

const CACHE_NAME = 'sar-x-v1';
const ASSETS_TO_CACHE = [
  '/',
  '/manifest.json',
  'https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap'
];
const AUTH_CACHE_BYPASS_PREFIXES = ['/login', '/logout', '/sifre-yenile', '/sifre-sifirla-talep'];

// Yükleme sırasında kritik dosyaları önbelleğe al
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS_TO_CACHE))
  );
  self.skipWaiting(); // Yeni versiyonu hemen devreye al
});

// İnternet yoksa önbellekten getir (SADECE GET İSTEKLERİ İÇİN)
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return; // POST isteklerini önbellekte arama!
  const requestUrl = new URL(event.request.url);

  if (
    requestUrl.origin === self.location.origin &&
    AUTH_CACHE_BYPASS_PREFIXES.some((prefix) => requestUrl.pathname === prefix || requestUrl.pathname.startsWith(prefix + '/'))
  ) {
    return;
  }

  event.respondWith(
    fetch(event.request).catch(() => {
      return caches.match(event.request);
    })
  );
});

// --- OFFLINE SYNC (BACKGROUND SYNC) BÖLÜMÜ ---

async function getDB() {
    return await idb.openDB('SAR_Offline_DB', 1);
}

// Cihaz internete bağlandığında işletim sistemi tarafından tetiklenir
self.addEventListener('sync', function(event) {
    if (event.tag === 'bakim-senkronize-et') {
        event.waitUntil(bekleyenBakimlariGonder());
    }
});

async function bekleyenBakimlariGonder() {
    const db = await getDB();
    // Bekleyen tüm kayıtları al
    const bekleyenler = await db.getAll('bekleyen_bakimlar');

    for (const kayit of bekleyenler) {
        try {
            // Flask'ın anlayacağı formata (application/x-www-form-urlencoded) çevir
            const bodyParams = new URLSearchParams();
            bodyParams.append('not', kayit.not);
            bodyParams.append('maliyet', kayit.maliyet);

            // Flask sunucusuna fırlat
            const response = await fetch(`/bakim-kaydet/${kayit.malzeme_id}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: bodyParams
            });

            // Başarılıysa IndexedDB'den temizle
            if (response.ok || response.redirected) {
                await db.delete('bekleyen_bakimlar', kayit.id);
                console.log(`Offline kayıt başarıyla senkronize edildi: Malzeme ${kayit.malzeme_id}`);
            }
        } catch (error) {
            console.error('Senkronizasyon başarısız, ağ gelince tekrar denenecek.', error);
            // Hata fırlatarak Service Worker'a "işlem bitmedi, sonra tekrar dene" diyoruz
            throw error; 
        }
    }
}
