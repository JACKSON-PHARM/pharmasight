/**
 * Platform Admin (admin.html): Marketing Settings (public contact details).
 *
 * Backs /api/admin/site-settings and is consumed by /marketing/* via /api/public/site-settings.
 */

export async function init() {
    const mount = document.getElementById('marketing-settings-mount');
    if (!mount) return;

    const esc = (s) => {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    };

    const api = window.API?.admin?.siteSettings;
    if (!api) {
        mount.innerHTML = `
            <div class="card" style="padding:16px;">
                <h2 style="margin:0 0 8px 0;">Marketing Settings</h2>
                <p style="margin:0; color:#b91c1c;">API client not loaded for /api/admin/site-settings.</p>
            </div>
        `;
        return;
    }

    mount.innerHTML = `
        <div class="card" style="padding:16px; max-width: 860px;">
            <h2 style="margin:0 0 8px 0;">Marketing Settings</h2>
            <p style="margin:0 0 14px 0; color:#475569; font-size:0.92rem; line-height:1.4;">
                These values power the public website footer and WhatsApp links under <code>/marketing/*</code>.
                Update here to avoid hardcoding contact details in HTML.
            </p>

            <form id="mk-form" style="display:grid; gap:12px;">
                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:12px;">
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">Support email</label>
                        <input id="mk-support-email" type="email" placeholder="support@pharmasight.co.ke" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                    </div>
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">Sales email</label>
                        <input id="mk-sales-email" type="email" placeholder="sales@pharmasight.co.ke" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                    </div>
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">Phone</label>
                        <input id="mk-phone" type="text" placeholder="+254 7xx xxx xxx" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                    </div>
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">WhatsApp</label>
                        <input id="mk-whatsapp" type="text" placeholder="0708476318 or +254708476318" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                        <div style="margin-top:6px; font-size:0.8rem; color:#64748b;">
                            Accepts local (07...) or international (+254...). Marketing converts to WhatsApp click-to-chat.
                        </div>
                    </div>
                </div>

                <div>
                    <label style="display:block; font-weight:600; margin-bottom:4px;">Address</label>
                    <textarea id="mk-address" rows="3" placeholder="Company address / location" style="width:100%; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px; resize: vertical;"></textarea>
                </div>

                <hr style="border:none;border-top:1px solid #e2e8f0;margin:16px 0;">
                <h3 style="margin:0 0 8px 0; font-size:1rem;">Marketing images</h3>
                <p style="margin:0 0 12px 0; color:#64748b; font-size:0.88rem; line-height:1.4;">
                    Uploads go to the Supabase Storage bucket <code>marketing-public</code>. Public URLs are saved here and used by <code>/marketing/*</code> (logo header, favicon link, OG image meta).
                    PNG or JPEG, max 2&nbsp;MB.
                </p>

                <div style="display:grid; gap:14px;">
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">Logo URL</label>
                        <input id="mk-logo-url" type="url" placeholder="https://… (optional — or upload below)" style="width:100%; max-width:560px; padding:8px 10px; border:1px solid #e2e8f0; border-radius:8px;">
                        <div style="margin-top:8px; display:flex; flex-wrap:wrap; gap:8px; align-items:center;">
                            <input id="mk-logo-file" type="file" accept="image/png,image/jpeg">
                            <button type="button" class="btn btn-secondary" id="mk-logo-upload">Upload logo</button>
                        </div>
                        <div style="margin-top:8px;"><img id="mk-preview-logo" alt="" style="max-height:40px; display:none; border-radius:4px;"></div>
                    </div>
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">Favicon</label>
                        <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center;">
                            <input id="mk-favicon-file" type="file" accept="image/png,image/jpeg">
                            <button type="button" class="btn btn-secondary" id="mk-favicon-upload">Upload favicon</button>
                        </div>
                        <div style="margin-top:6px; font-size:0.82rem; color:#64748b; word-break:break-all;" id="mk-url-favicon"></div>
                        <div style="margin-top:8px;"><img id="mk-preview-favicon" alt="" style="max-height:32px; display:none; border-radius:4px;"></div>
                    </div>
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">Hero image (optional)</label>
                        <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center;">
                            <input id="mk-hero-file" type="file" accept="image/png,image/jpeg">
                            <button type="button" class="btn btn-secondary" id="mk-hero-upload">Upload hero</button>
                        </div>
                        <div style="margin-top:6px; font-size:0.82rem; color:#64748b; word-break:break-all;" id="mk-url-hero"></div>
                        <div style="margin-top:8px;"><img id="mk-preview-hero" alt="" style="max-height:80px; display:none; border-radius:4px;"></div>
                    </div>
                    <div>
                        <label style="display:block; font-weight:600; margin-bottom:4px;">Open Graph image</label>
                        <div style="display:flex; flex-wrap:wrap; gap:8px; align-items:center;">
                            <input id="mk-og-file" type="file" accept="image/png,image/jpeg">
                            <button type="button" class="btn btn-secondary" id="mk-og-upload">Upload OG image</button>
                        </div>
                        <div style="margin-top:6px; font-size:0.82rem; color:#64748b; word-break:break-all;" id="mk-url-og"></div>
                        <div style="margin-top:8px;"><img id="mk-preview-og" alt="" style="max-height:80px; display:none; border-radius:4px;"></div>
                    </div>
                </div>

                <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:4px;">
                    <button type="submit" class="btn btn-primary" id="mk-save">Save</button>
                    <span id="mk-status" style="color:#64748b; font-size:0.9rem;"></span>
                </div>
            </form>
        </div>
    `;

    const elSupport = document.getElementById('mk-support-email');
    const elSales = document.getElementById('mk-sales-email');
    const elPhone = document.getElementById('mk-phone');
    const elWa = document.getElementById('mk-whatsapp');
    const elAddr = document.getElementById('mk-address');
    const elLogoUrl = document.getElementById('mk-logo-url');
    const form = document.getElementById('mk-form');
    const status = document.getElementById('mk-status');
    const saveBtn = document.getElementById('mk-save');

    function setPreview(imgEl, url) {
        if (!imgEl) return;
        const u = (url || '').trim();
        if (u) {
            imgEl.src = u;
            imgEl.style.display = 'block';
        } else {
            imgEl.removeAttribute('src');
            imgEl.style.display = 'none';
        }
    }

    async function load() {
        try {
            if (status) status.textContent = 'Loading…';
            const s = await api.get();
            if (elSupport) elSupport.value = (s && s.support_email) ? String(s.support_email) : '';
            if (elSales) elSales.value = (s && s.sales_email) ? String(s.sales_email) : '';
            if (elPhone) elPhone.value = (s && s.phone) ? String(s.phone) : '';
            if (elWa) elWa.value = (s && s.whatsapp) ? String(s.whatsapp) : '';
            if (elAddr) elAddr.value = (s && s.address) ? String(s.address) : '';
            if (elLogoUrl) elLogoUrl.value = (s && s.logo_url) ? String(s.logo_url) : '';
            const mi = (s && s.marketing_images) ? s.marketing_images : {};
            const uf = document.getElementById('mk-url-favicon');
            const uh = document.getElementById('mk-url-hero');
            const uo = document.getElementById('mk-url-og');
            if (uf) uf.textContent = mi.favicon ? String(mi.favicon) : '';
            if (uh) uh.textContent = mi.hero ? String(mi.hero) : '';
            if (uo) uo.textContent = mi.og_image ? String(mi.og_image) : '';
            setPreview(document.getElementById('mk-preview-logo'), s && s.logo_url ? String(s.logo_url) : '');
            setPreview(document.getElementById('mk-preview-favicon'), mi.favicon ? String(mi.favicon) : '');
            setPreview(document.getElementById('mk-preview-hero'), mi.hero ? String(mi.hero) : '');
            setPreview(document.getElementById('mk-preview-og'), mi.og_image ? String(mi.og_image) : '');
            if (status) status.textContent = '';
        } catch (e) {
            if (status) status.textContent = 'Failed to load settings: ' + esc(e.message || 'Error');
        }
    }

    async function uploadAsset(kind, fileInput) {
        const up = api.uploadMarketingImage;
        if (!up || !fileInput) return;
        const file = fileInput.files && fileInput.files[0];
        if (!file) {
            if (status) status.textContent = 'Choose an image file first.';
            return;
        }
        try {
            if (status) status.textContent = 'Uploading…';
            await up(kind, file);
            fileInput.value = '';
            if (status) status.textContent = 'Uploaded.';
            setTimeout(() => {
                if (status && status.textContent === 'Uploaded.') status.textContent = '';
            }, 2500);
            await load();
        } catch (e) {
            if (status) status.textContent = 'Upload failed: ' + esc(e.message || 'Error');
        }
    }

    const logoUploadBtn = document.getElementById('mk-logo-upload');
    const favUploadBtn = document.getElementById('mk-favicon-upload');
    const heroUploadBtn = document.getElementById('mk-hero-upload');
    const ogUploadBtn = document.getElementById('mk-og-upload');
    if (logoUploadBtn) logoUploadBtn.addEventListener('click', () => uploadAsset('logo', document.getElementById('mk-logo-file')));
    if (favUploadBtn) favUploadBtn.addEventListener('click', () => uploadAsset('favicon', document.getElementById('mk-favicon-file')));
    if (heroUploadBtn) heroUploadBtn.addEventListener('click', () => uploadAsset('hero', document.getElementById('mk-hero-file')));
    if (ogUploadBtn) ogUploadBtn.addEventListener('click', () => uploadAsset('og_image', document.getElementById('mk-og-file')));

    if (form) {
        form.addEventListener('submit', async (ev) => {
            ev.preventDefault();
            try {
                if (status) status.textContent = 'Saving…';
                if (saveBtn) saveBtn.disabled = true;
                const payload = {
                    support_email: (elSupport?.value || '').trim(),
                    sales_email: (elSales?.value || '').trim(),
                    phone: (elPhone?.value || '').trim(),
                    whatsapp: (elWa?.value || '').trim(),
                    address: (elAddr?.value || '').trim(),
                    logo_url: (elLogoUrl?.value || '').trim(),
                };
                await api.put(payload);
                if (status) status.textContent = 'Saved.';
                setTimeout(() => { if (status && status.textContent === 'Saved.') status.textContent = ''; }, 2500);
            } catch (e) {
                if (status) status.textContent = 'Save failed: ' + esc(e.message || 'Error');
            } finally {
                if (saveBtn) saveBtn.disabled = false;
            }
        });
    }

    await load();
}

