(function (window) {
    "use strict";
    var LAST_PASSKEY_IDENTIFIER_STORAGE_KEY = "sarx-passkey-login-identifier";

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

    function passkeyLoginErrorMessage(error) {
        if (error && error.userMessage) {
            return String(error.userMessage);
        }
        var name = String((error && error.name) || "").trim();
        if (name === "NotSupportedError") {
            return "Bu cihaz veya tarayıcı passkey ile girişi desteklemiyor.";
        }
        if (name === "SecurityError") {
            return "Passkey ile giriş için güvenli bağlantı (HTTPS veya localhost) gerekiyor.";
        }
        if (name === "InvalidStateError" || name === "NotFoundError") {
            return "Bu cihazda bu hesap için kullanılabilir passkey bulunamadı.";
        }
        var rawMessage = String((error && error.message) || "").trim();
        if (rawMessage) {
            return rawMessage;
        }
        return "Biyometrik giriş tamamlanamadı.";
    }

    function isDisallowedGovTrEmail(value) {
        var normalized = String(value || "").trim().toLowerCase();
        if (!normalized || normalized.indexOf("@") === -1) {
            return false;
        }
        var domain = normalized.split("@").pop().replace(/\.+$/g, "");
        return domain === "gov.tr" || domain.endsWith(".gov.tr");
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
        if (
            !window.isSecureContext ||
            !window.PublicKeyCredential ||
            !navigator.credentials ||
            typeof navigator.credentials.get !== "function"
        ) {
            return false;
        }
        if (typeof window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable === "function") {
            try {
                await window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
            } catch (_error) {
                // Bazı tarayıcılarda bu kontrol hata verebilir; temel WebAuthn API varsa devam edilir.
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
        var usernameInput = document.querySelector('input[name="kullanici_adi"]');
        var captchaInput = document.getElementById(settings.captchaInputId || "");
        var captchaTokenInput = document.getElementById(settings.captchaTokenId || "");
        if (!button || !settings.beginUrl || !settings.finishUrl) {
            return;
        }

        if (!(await supportsPasskeys())) {
            return;
        }

        try {
            if (usernameInput && !String(usernameInput.value || "").trim() && window.localStorage) {
                var rememberedIdentifier = String(window.localStorage.getItem(LAST_PASSKEY_IDENTIFIER_STORAGE_KEY) || "").trim();
                if (rememberedIdentifier) {
                    usernameInput.value = rememberedIdentifier;
                }
            }
        } catch (_storageError) {
            // localStorage desteklenmiyorsa sessiz devam.
        }

        button.hidden = false;

        button.addEventListener("click", async function () {
            var loginIdentifier = String((usernameInput && usernameInput.value) || "").trim().toLowerCase();
            var rememberInput = document.querySelector('input[name="remember_me"]');
            var blockedGovTrMessage = 'Güvenlik nedeniyle "gov.tr" uzantılı e-posta adresleri kabul edilmemektedir.';
            if (loginIdentifier && isDisallowedGovTrEmail(loginIdentifier)) {
                if (usernameInput) {
                    usernameInput.setCustomValidity(blockedGovTrMessage);
                    usernameInput.reportValidity();
                }
                showToast(blockedGovTrMessage, "warning");
                return;
            }
            if (usernameInput) {
                usernameInput.setCustomValidity("");
            }
            if (!loginIdentifier) {
                var requiredIdentifierMessage = "Biyometrik giriş için önce kullanıcı adınızı (e-posta) girin.";
                if (usernameInput) {
                    usernameInput.setCustomValidity(requiredIdentifierMessage);
                    usernameInput.reportValidity();
                    usernameInput.focus();
                }
                showToast(requiredIdentifierMessage, "warning");
                return;
            }
            setLoadingState(button, true);
            try {
                var beginPayload = {
                    remember_me: Boolean(rememberInput && rememberInput.checked),
                    login_identifier: loginIdentifier
                };
                var begin = await postJson(settings.beginUrl, beginPayload);
                var assertion = await navigator.credentials.get({
                    publicKey: normalizeRequestOptions(begin.public_key || {})
                });
                if (!assertion || !assertion.response) {
                    throw new Error("Passkey alınamadı.");
                }
                var finishPayload = {
                    id: assertion.id,
                    rawId: toBase64Url(assertion.rawId),
                    type: assertion.type,
                    response: {
                        clientDataJSON: toBase64Url(assertion.response.clientDataJSON),
                        authenticatorData: toBase64Url(assertion.response.authenticatorData),
                        signature: toBase64Url(assertion.response.signature),
                        userHandle: assertion.response.userHandle ? toBase64Url(assertion.response.userHandle) : ""
                    }
                };
                if (captchaInput && String(captchaInput.value || "").trim()) {
                    finishPayload.security_verification = String(captchaInput.value || "").trim();
                }
                if (captchaTokenInput && String(captchaTokenInput.value || "").trim()) {
                    finishPayload.security_verification_token = String(captchaTokenInput.value || "").trim();
                }
                var finish = await postJson(settings.finishUrl, finishPayload);
                try {
                    if (window.localStorage) {
                        window.localStorage.setItem(LAST_PASSKEY_IDENTIFIER_STORAGE_KEY, loginIdentifier);
                    }
                } catch (_storageWriteError) {
                    // localStorage desteklenmiyorsa sessiz devam.
                }
                if (finish.redirect_url) {
                    window.location.assign(finish.redirect_url);
                    return;
                }
                window.location.reload();
            } catch (error) {
                if (error && (error.name === "AbortError" || error.name === "NotAllowedError")) {
                    return;
                }
                showToast(passkeyLoginErrorMessage(error), "warning");
            } finally {
                setLoadingState(button, false);
            }
        });
    }

    async function initRegistration(config) {
        var settings = Object.assign({}, config || {});
        var button = document.getElementById(settings.buttonId || "");
        if (!button || !settings.beginUrl || !settings.finishUrl) {
            return false;
        }

        if (!(await supportsPasskeys())) {
            return false;
        }
        if (!settings.keepHidden) {
            button.hidden = false;
        }

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
                if (typeof settings.onSuccess === "function") {
                    try {
                        settings.onSuccess(finish);
                    } catch (_error) {
                        // Keep passkey registration success even if optional callback throws.
                    }
                }
            } catch (error) {
                if (error && (error.name === "AbortError" || error.name === "NotAllowedError")) {
                    return;
                }
                showToast((error && error.userMessage) || error.message || "Passkey kaydı tamamlanamadı.", "warning");
            } finally {
                setLoadingState(button, false);
            }
        });
        return true;
    }

    function _readCredentialLabel(item, fallbackIndex) {
        return String(item && item.label ? item.label : ("Cihaz " + fallbackIndex)).trim();
    }

    function _buildCredentialMeta(item) {
        var parts = [];
        var createdAt = String((item && item.created_at) || "").trim();
        var lastUsedAt = String((item && item.last_used_at) || "").trim();
        var transports = Array.isArray(item && item.transports) ? item.transports.filter(Boolean).map(String) : [];
        if (createdAt) parts.push("Kayıt: " + createdAt);
        if (lastUsedAt) parts.push("Son kullanım: " + lastUsedAt);
        if (transports.length) parts.push("Taşıyıcı: " + transports.join(", "));
        return parts.join(" | ");
    }

    function _createCredentialRow(item, index) {
        var row = document.createElement("div");
        row.className = "settings-passkey-item";

        var content = document.createElement("div");
        content.className = "settings-passkey-item-main";

        var title = document.createElement("div");
        title.className = "settings-passkey-item-title";
        title.textContent = _readCredentialLabel(item, index + 1);

        var meta = document.createElement("div");
        meta.className = "settings-passkey-item-meta";
        meta.textContent = _buildCredentialMeta(item) || "Bu passkey kaydı aktif.";

        content.appendChild(title);
        content.appendChild(meta);

        var actionButton = document.createElement("button");
        actionButton.type = "button";
        actionButton.className = "btn settings-passkey-delete";
        actionButton.textContent = "Sil";
        actionButton.setAttribute("data-passkey-revoke-id", String(item.id || ""));
        actionButton.setAttribute("data-passkey-label", _readCredentialLabel(item, index + 1));

        row.appendChild(content);
        row.appendChild(actionButton);
        return row;
    }

    function initManagementList(config) {
        var settings = Object.assign({}, config || {});
        var container = document.getElementById(settings.listContainerId || "");
        var emptyState = document.getElementById(settings.emptyStateId || "");
        var refreshButton = document.getElementById(settings.refreshButtonId || "");
        if (!container || !settings.listUrl || !settings.revokeUrl) {
            return { refresh: function () {} };
        }

        async function refreshList() {
            container.setAttribute("aria-busy", "true");
            try {
                var listResponse = await getJson(settings.listUrl);
                var credentials = Array.isArray(listResponse.credentials) ? listResponse.credentials : [];
                container.innerHTML = "";
                if (!credentials.length) {
                    if (emptyState) {
                        emptyState.hidden = false;
                    }
                    return;
                }
                if (emptyState) {
                    emptyState.hidden = true;
                }
                credentials.forEach(function (item, index) {
                    container.appendChild(_createCredentialRow(item, index));
                });
            } catch (error) {
                showToast((error && error.userMessage) || "Passkey kayıtları getirilemedi.", "warning");
            } finally {
                container.removeAttribute("aria-busy");
            }
        }

        container.addEventListener("click", async function (event) {
            var revokeButton = event.target && event.target.closest ? event.target.closest("[data-passkey-revoke-id]") : null;
            if (!revokeButton) return;
            var credentialId = String(revokeButton.getAttribute("data-passkey-revoke-id") || "").trim();
            var credentialLabel = String(revokeButton.getAttribute("data-passkey-label") || "Seçili cihaz").trim();
            if (!credentialId) return;
            if (!window.confirm('"' + credentialLabel + '" kaydı kaldırılacak. Onaylıyor musunuz?')) {
                return;
            }
            setLoadingState(revokeButton, true);
            try {
                var revokeResponse = await postJson(settings.revokeUrl, { credential_id: credentialId });
                showToast(String(revokeResponse.message || "Passkey kaydı kaldırıldı."), "success");
                await refreshList();
            } catch (error) {
                showToast((error && error.userMessage) || "Passkey kaydı kaldırılamadı.", "warning");
            } finally {
                setLoadingState(revokeButton, false);
            }
        });

        if (refreshButton) {
            refreshButton.addEventListener("click", refreshList);
        }

        refreshList();
        return { refresh: refreshList };
    }

    function initManagement(config) {
        var settings = Object.assign({}, config || {});
        var button = document.getElementById(settings.buttonId || "");
        if (!button) {
            return;
        }
        if (settings.listContainerId) {
            initManagementList(settings);
            return;
        }
        button.hidden = false;
        button.addEventListener("click", function () {
            showToast("Passkey yönetimi Ayarlar ekranına taşındı.", "info");
            if (settings.settingsUrl) {
                window.location.assign(settings.settingsUrl);
            }
        });
    }

    window.SARXPasskey = {
        initLogin: initLogin,
        initRegistration: initRegistration,
        initManagement: initManagement,
        initManagementList: initManagementList
    };
})(window);
