(function (window) {
    "use strict";

    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? String(meta.getAttribute("content") || "") : "";
    }

    function showToast(message, tone) {
        if (typeof window.showLoginToast === "function") {
            window.showLoginToast(message, tone || "info", 3600);
            return;
        }
        if (typeof window.showToast === "function") {
            window.showToast({ message: message, type: tone || "info", duration: 3600 });
        }
    }

    function toBase64Url(buffer) {
        var bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
        var binary = "";
        for (var i = 0; i < bytes.length; i += 1) {
            binary += String.fromCharCode(bytes[i]);
        }
        return window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
    }

    function fromBase64Url(value) {
        var normalized = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
        while (normalized.length % 4) {
            normalized += "=";
        }
        var binary = window.atob(normalized);
        var bytes = new Uint8Array(binary.length);
        for (var i = 0; i < binary.length; i += 1) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }

    function normalizeCredentialDescriptors(list) {
        if (!Array.isArray(list)) return [];
        return list.map(function (item) {
            var descriptor = Object.assign({}, item);
            descriptor.id = fromBase64Url(item.id);
            return descriptor;
        });
    }

    function normalizeCreationOptions(options) {
        var cfg = Object.assign({}, options || {});
        cfg.challenge = fromBase64Url(cfg.challenge);
        if (cfg.user && cfg.user.id) {
            cfg.user = Object.assign({}, cfg.user, { id: fromBase64Url(cfg.user.id) });
        }
        cfg.excludeCredentials = normalizeCredentialDescriptors(cfg.excludeCredentials);
        return cfg;
    }

    function normalizeRequestOptions(options) {
        var cfg = Object.assign({}, options || {});
        cfg.challenge = fromBase64Url(cfg.challenge);
        cfg.allowCredentials = normalizeCredentialDescriptors(cfg.allowCredentials);
        return cfg;
    }

    async function requestJson(url, options) {
        var cfg = Object.assign({ method: "POST", payload: null }, options || {});
        var headers = {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest"
        };
        var csrfToken = getCsrfToken();
        if (csrfToken) {
            headers["X-CSRFToken"] = csrfToken;
        }
        var response = await window.fetch(url, {
            method: String(cfg.method || "POST").toUpperCase(),
            credentials: "same-origin",
            headers: headers,
            body: cfg.payload === null && String(cfg.method || "POST").toUpperCase() === "GET"
                ? null
                : JSON.stringify(cfg.payload || {})
        });
        var data = {};
        try {
            data = await response.json();
        } catch (_error) {
            data = {};
        }
        if (!response.ok || data.status === "error") {
            var error = new Error(String(data.message || "Passkey işlemi tamamlanamadı."));
            error.name = String(data.code || error.name);
            error.userMessage = String(data.message || "Passkey işlemi tamamlanamadı.");
            throw error;
        }
        return data;
    }

    async function postJson(url, payload) {
        return requestJson(url, { method: "POST", payload: payload });
    }

    async function getJson(url) {
        return requestJson(url, { method: "GET", payload: null });
    }

    async function supportsPasskeys() {
        if (!window.isSecureContext || !window.PublicKeyCredential || !navigator.credentials) {
            return false;
        }
        if (typeof window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable === "function") {
            try {
                return await window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
            } catch (_error) {
                return true;
            }
        }
        return true;
    }

    function setLoadingState(button, isLoading) {
        if (!button) return;
        button.disabled = Boolean(isLoading);
        button.classList.toggle("is-loading", Boolean(isLoading));
    }

    async function initLogin(config) {
        var settings = Object.assign({}, config || {});
        var button = document.getElementById(settings.buttonId || "");
        var captchaInput = document.getElementById(settings.captchaInputId || "");
        var captchaTokenInput = document.getElementById(settings.captchaTokenId || "");
        if (!button || !captchaInput || !captchaTokenInput || !settings.beginUrl || !settings.finishUrl) {
            return;
        }

        if (!(await supportsPasskeys())) {
            return;
        }
        button.hidden = false;

        button.addEventListener("click", async function () {
            if (!String(captchaInput.value || "").trim()) {
                showToast("Biyometrik girişten önce güvenlik kodunu girin.", "warning");
                captchaInput.focus({ preventScroll: true });
                return;
            }
            if (!String(captchaTokenInput.value || "").trim()) {
                showToast("Doğrulama kodu yenilenmiş olabilir. Lütfen güvenlik kodunu tekrar deneyin.", "warning");
                return;
            }

            var rememberInput = document.querySelector('input[name="remember_me"]');
            setLoadingState(button, true);
            try {
                var begin = await postJson(settings.beginUrl, {
                    remember_me: Boolean(rememberInput && rememberInput.checked)
                });
                var assertion = await navigator.credentials.get({
                    publicKey: normalizeRequestOptions(begin.public_key || {})
                });
                if (!assertion || !assertion.response) {
                    throw new Error("Passkey alınamadı.");
                }
                var finish = await postJson(settings.finishUrl, {
                    id: assertion.id,
                    rawId: toBase64Url(assertion.rawId),
                    type: assertion.type,
                    response: {
                        clientDataJSON: toBase64Url(assertion.response.clientDataJSON),
                        authenticatorData: toBase64Url(assertion.response.authenticatorData),
                        signature: toBase64Url(assertion.response.signature),
                        userHandle: assertion.response.userHandle ? toBase64Url(assertion.response.userHandle) : ""
                    },
                    security_verification: String(captchaInput.value || "").trim(),
                    security_verification_token: String(captchaTokenInput.value || "").trim()
                });
                if (finish.redirect_url) {
                    window.location.assign(finish.redirect_url);
                    return;
                }
                window.location.reload();
            } catch (error) {
                if (error && (error.name === "AbortError" || error.name === "NotAllowedError")) {
                    return;
                }
                showToast((error && error.userMessage) || "Biyometrik giriş tamamlanamadı.", "warning");
            } finally {
                setLoadingState(button, false);
            }
        });
    }

    async function initRegistration(config) {
        var settings = Object.assign({}, config || {});
        var button = document.getElementById(settings.buttonId || "");
        if (!button || !settings.beginUrl || !settings.finishUrl) {
            return;
        }

        if (!(await supportsPasskeys())) {
            return;
        }
        button.hidden = false;

        button.addEventListener("click", async function () {
            setLoadingState(button, true);
            try {
                var begin = await postJson(settings.beginUrl, {});
                var credential = await navigator.credentials.create({
                    publicKey: normalizeCreationOptions(begin.public_key || {})
                });
                if (!credential || !credential.response) {
                    throw new Error("Passkey oluşturulamadı.");
                }
                if (!credential.response.attestationObject) {
                    throw new Error("Passkey verisi eksik döndü.");
                }
                var finish = await postJson(settings.finishUrl, {
                    id: credential.id,
                    rawId: toBase64Url(credential.rawId),
                    type: credential.type,
                    response: {
                        clientDataJSON: toBase64Url(credential.response.clientDataJSON),
                        attestationObject: toBase64Url(credential.response.attestationObject),
                        transports: typeof credential.response.getTransports === "function" ? credential.response.getTransports() : []
                    }
                });
                showToast(String(finish.message || "Biyometrik giriş bu cihaz için etkinleştirildi."), "success");
            } catch (error) {
                if (error && (error.name === "AbortError" || error.name === "NotAllowedError")) {
                    return;
                }
                showToast((error && error.userMessage) || error.message || "Passkey kaydı tamamlanamadı.", "warning");
            } finally {
                setLoadingState(button, false);
            }
        });
    }

    async function initManagement(config) {
        var settings = Object.assign({}, config || {});
        var button = document.getElementById(settings.buttonId || "");
        if (!button || !settings.listUrl || !settings.revokeUrl) {
            return;
        }
        button.hidden = false;

        button.addEventListener("click", async function () {
            setLoadingState(button, true);
            try {
                var listResponse = await getJson(settings.listUrl);
                var credentials = Array.isArray(listResponse.credentials) ? listResponse.credentials : [];
                if (!credentials.length) {
                    showToast("Bu hesap için kayıtlı aktif passkey bulunmuyor.", "info");
                    return;
                }
                var lines = credentials.map(function (item, index) {
                    var label = String(item.label || ("Cihaz " + (index + 1))).trim();
                    var createdAt = String(item.created_at || "").trim();
                    var lastUsedAt = String(item.last_used_at || "").trim();
                    var details = [];
                    if (createdAt) details.push("Kayıt: " + createdAt);
                    if (lastUsedAt) details.push("Son kullanım: " + lastUsedAt);
                    return (index + 1) + ") " + label + (details.length ? " [" + details.join(" | ") + "]" : "");
                });
                var selected = window.prompt(
                    "Kaldırmak istediğiniz passkey için numara girin. İptal için boş bırakın.\n\n" + lines.join("\n")
                );
                if (selected === null || String(selected).trim() === "") {
                    return;
                }
                var selectedIndex = Number.parseInt(String(selected).trim(), 10) - 1;
                if (!Number.isFinite(selectedIndex) || selectedIndex < 0 || selectedIndex >= credentials.length) {
                    showToast("Geçerli bir passkey numarası girin.", "warning");
                    return;
                }
                var selectedCredential = credentials[selectedIndex];
                var confirmText = "\"" + String(selectedCredential.label || ("Cihaz " + (selectedIndex + 1))) + "\" kaydı kaldırılacak. Onaylıyor musunuz?";
                if (!window.confirm(confirmText)) {
                    return;
                }
                var revokeResponse = await postJson(settings.revokeUrl, { credential_id: selectedCredential.id });
                showToast(String(revokeResponse.message || "Passkey kaydı kaldırıldı."), "success");
            } catch (error) {
                showToast((error && error.userMessage) || "Passkey kayıtları yönetilemedi.", "warning");
            } finally {
                setLoadingState(button, false);
            }
        });
    }

    window.SARXPasskey = {
        initLogin: initLogin,
        initRegistration: initRegistration,
        initManagement: initManagement
    };
})(window);
