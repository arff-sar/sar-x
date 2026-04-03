const CACHE_NAME = 'sar-x-v3';
const ASSETS_TO_CACHE = [
  '/manifest.json',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
  '/static/img/icon-maskable-512.png'
];
const AUTH_CACHE_BYPASS_PREFIXES = ['/login', '/logout', '/sifre-yenile', '/sifre-sifirla-talep'];
const OFFLINE_DB_NAME = 'SAR_Offline_DB';
const OFFLINE_DB_VERSION = 2;
const OFFLINE_STORE_NAME = 'bekleyen_bakimlar';
const CSRF_TOKEN_ENDPOINT = '/api/csrf-token';

// Yükleme sırasında kritik dosyaları önbelleğe al
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS_TO_CACHE))
  );
  self.skipWaiting(); // Yeni versiyonu hemen devreye al
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

// İnternet yoksa önbellekten getir (SADECE GET İSTEKLERİ İÇİN)
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return; // POST isteklerini önbellekte arama!

  let requestUrl;
  try {
    requestUrl = new URL(event.request.url);
  } catch (_error) {
    return;
  }

  // CSP/3rd-party kaynakları SW tarafında intercept etmeyelim.
  if (requestUrl.origin !== self.location.origin) {
    return;
  }

  if (event.request.mode === 'navigate') {
    return;
  }

  if (
    AUTH_CACHE_BYPASS_PREFIXES.some((prefix) => requestUrl.pathname === prefix || requestUrl.pathname.startsWith(prefix + '/'))
  ) {
    return;
  }

  event.respondWith((async () => {
    try {
      return await fetch(event.request);
    } catch (_networkError) {
      try {
        const cachedResponse = await caches.match(event.request);
        if (cachedResponse) {
          return cachedResponse;
        }
      } catch (_cacheError) {
        // Cache erişimi de hata verirse güvenli fallback döneriz.
      }
      return new Response('Offline', {
        status: 503,
        statusText: 'Offline',
      });
    }
  })());
});

// --- OFFLINE SYNC (BACKGROUND SYNC) BÖLÜMÜ ---

async function getDB() {
    if (!self.indexedDB) {
        throw new Error('IndexedDB desteği bulunamadı.');
    }

    const database = await new Promise((resolve, reject) => {
        const openRequest = self.indexedDB.open(OFFLINE_DB_NAME, OFFLINE_DB_VERSION);

        openRequest.onupgradeneeded = () => {
            const db = openRequest.result;
            if (!db.objectStoreNames.contains(OFFLINE_STORE_NAME)) {
                db.createObjectStore('bekleyen_bakimlar', { keyPath: 'id', autoIncrement: true });
            }
        };

        openRequest.onsuccess = () => resolve(openRequest.result);
        openRequest.onerror = () => reject(openRequest.error || new Error('IndexedDB açılamadı.'));
    });

    const runTransaction = (storeName, mode, executor) => new Promise((resolve, reject) => {
        const tx = database.transaction(storeName, mode);
        const store = tx.objectStore(storeName);
        let request;
        try {
            request = executor(store);
        } catch (error) {
            reject(error);
            return;
        }

        tx.oncomplete = () => resolve(request ? request.result : undefined);
        tx.onabort = () => reject(tx.error || new Error('IndexedDB transaction abort oldu.'));
        tx.onerror = () => reject(tx.error || new Error('IndexedDB transaction hatası.'));
    });

    return {
        getAll(storeName) {
            return runTransaction(storeName, 'readonly', (store) => store.getAll());
        },
        delete(storeName, key) {
            return runTransaction(storeName, 'readwrite', (store) => store.delete(key));
        },
        close() {
            try {
                database.close();
            } catch (_error) {
                // no-op
            }
        }
    };
}

async function notifyOfflineSyncClients(type, message, extra) {
    let clientList = [];
    try {
        clientList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    } catch (_error) {
        clientList = [];
    }

    const payload = {
        type,
        message: String(message || ''),
        ...(extra && typeof extra === 'object' ? extra : {}),
    };

    for (const client of clientList) {
        try {
            client.postMessage(payload);
        } catch (_error) {
            // no-op
        }
    }
}

async function fetchCsrfTokenForSync() {
    const response = await fetch(CSRF_TOKEN_ENDPOINT, {
        method: 'GET',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: {
            'Accept': 'application/json',
            'X-SARX-Client-Mode': 'standalone',
        },
    });

    if (!response.ok) {
        throw new Error(`CSRF token endpoint hatası (${response.status})`);
    }

    let payload = {};
    try {
        payload = await response.json();
    } catch (_error) {
        payload = {};
    }
    const csrfToken = String(payload.csrf_token || '').trim();
    if (!csrfToken) {
        throw new Error('CSRF token üretilemedi.');
    }
    return csrfToken;
}

// Cihaz internete bağlandığında işletim sistemi tarafından tetiklenir
self.addEventListener('sync', function(event) {
    if (event.tag === 'bakim-senkronize-et') {
        event.waitUntil(bekleyenBakimlariGonder());
    }
});

async function bekleyenBakimlariGonder() {
    const db = await getDB();
    try {
        // Bekleyen tüm kayıtları al
        const bekleyenler = await db.getAll(OFFLINE_STORE_NAME);
        if (!Array.isArray(bekleyenler) || bekleyenler.length === 0) {
            return;
        }

        const csrfToken = await fetchCsrfTokenForSync();
        let syncedCount = 0;

        for (const kayit of bekleyenler) {
            try {
                // Flask'ın anlayacağı formata (application/x-www-form-urlencoded) çevir
                const bodyParams = new URLSearchParams();
                bodyParams.append('not', String(kayit.not || ''));
                bodyParams.append('maliyet', String(kayit.maliyet || '0'));
                if (kayit.gelecek_bakim) {
                    bodyParams.append('gelecek_bakim', kayit.gelecek_bakim);
                }

                // Flask sunucusuna fırlat
                const response = await fetch(`/bakim-kaydet/${kayit.malzeme_id}`, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-CSRFToken': csrfToken,
                        'X-SARX-Offline-Sync': '1',
                        'X-SARX-Offline-Request-Id': String(kayit.offline_request_id || ''),
                    },
                    body: bodyParams
                });

                // Başarılıysa IndexedDB'den temizle
                if (response.ok || response.redirected) {
                    await db.delete(OFFLINE_STORE_NAME, kayit.id);
                    syncedCount += 1;
                    console.log(`Offline kayıt başarıyla senkronize edildi: Malzeme ${kayit.malzeme_id}`);
                    continue;
                }
                throw new Error(`Senkronizasyon reddedildi (${response.status})`);
            } catch (error) {
                console.error('Senkronizasyon başarısız, ağ gelince tekrar denenecek.', error);
                await notifyOfflineSyncClients(
                    'offline-sync-error',
                    'Çevrimdışı bakım kaydı senkronize edilemedi. Ağ geldiğinde tekrar denenecek.',
                    { recordId: kayit.id, malzemeId: kayit.malzeme_id }
                );
                // Hata fırlatarak Service Worker'a "işlem bitmedi, sonra tekrar dene" diyoruz
                throw error;
            }
        }
        if (syncedCount > 0) {
            await notifyOfflineSyncClients(
                'offline-sync-success',
                `${syncedCount} çevrimdışı bakım kaydı başarıyla senkronize edildi.`,
                { syncedCount: syncedCount }
            );
        }
    } finally {
        db.close();
    }
}
