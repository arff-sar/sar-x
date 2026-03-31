const CACHE_NAME = 'sar-x-v2';
const ASSETS_TO_CACHE = [
  '/manifest.json',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png'
];
const AUTH_CACHE_BYPASS_PREFIXES = ['/login', '/logout', '/sifre-yenile', '/sifre-sifirla-talep'];
const OFFLINE_DB_NAME = 'SAR_Offline_DB';
const OFFLINE_DB_VERSION = 2;
const OFFLINE_STORE_NAME = 'bekleyen_bakimlar';

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
  const requestUrl = new URL(event.request.url);

  if (event.request.mode === 'navigate') {
    return;
  }

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
    if (!self.indexedDB) {
        throw new Error('IndexedDB desteği bulunamadı.');
    }

    const database = await new Promise((resolve, reject) => {
        const openRequest = self.indexedDB.open(OFFLINE_DB_NAME, OFFLINE_DB_VERSION);

        openRequest.onupgradeneeded = () => {
            const db = openRequest.result;
            if (!db.objectStoreNames.contains(OFFLINE_STORE_NAME)) {
                db.createObjectStore(OFFLINE_STORE_NAME, { keyPath: 'id', autoIncrement: true });
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
                    await db.delete(OFFLINE_STORE_NAME, kayit.id);
                    console.log(`Offline kayıt başarıyla senkronize edildi: Malzeme ${kayit.malzeme_id}`);
                }
            } catch (error) {
                console.error('Senkronizasyon başarısız, ağ gelince tekrar denenecek.', error);
                // Hata fırlatarak Service Worker'a "işlem bitmedi, sonra tekrar dene" diyoruz
                throw error;
            }
        }
    } finally {
        db.close();
    }
}
