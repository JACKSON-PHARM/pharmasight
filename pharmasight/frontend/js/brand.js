/**
 * SightOps — centralized product branding (display strings + logo markup).
 * Storage keys remain `pharmasight_*` for backward compatibility with existing sessions.
 */
(function (global) {
    'use strict';

    var LOADING_MESSAGES = [
        'Syncing operations…',
        'Loading workspace…',
        'Preparing dashboard…',
        'Updating inventory intelligence…',
        'Checking branch network…',
    ];

    /** SightOps aperture mark (three sectors + focal center; matches sightops-mark.svg). */
    function svgIconMark(className, size) {
        var w = size != null ? size : 40;
        var cls = className ? ' class="' + String(className).replace(/"/g, '') + '"' : '';
        return (
            '<svg xmlns="http://www.w3.org/2000/svg"' + cls + ' width="' + w + '" height="' + w + '" viewBox="0 0 48 48" fill="none" aria-hidden="true">' +
            '<path d="M24 9 A15 15 0 0 1 36.98 31.2 L24 24 Z" fill="#142a4a"/>' +
            '<path d="M24 9 A15 15 0 0 1 36.98 31.2 L24 24 Z" fill="#0d9488" transform="rotate(120 24 24)"/>' +
            '<path d="M24 9 A15 15 0 0 1 36.98 31.2 L24 24 Z" fill="#9dc9b8" transform="rotate(240 24 24)"/>' +
            '<ellipse cx="24" cy="24.5" rx="6.2" ry="4.65" fill="#ffffff" transform="rotate(-11 24 24.5)"/>' +
            '<circle cx="24" cy="24.5" r="2.35" fill="#0f172a"/>' +
            '<circle cx="22.6" cy="23.45" r="0.7" fill="#ffffff" opacity="0.92"/>' +
            '</svg>'
        );
    }

    function svgIconMarkMono(className, size) {
        var w = size != null ? size : 48;
        var cls = className ? ' class="' + String(className).replace(/"/g, '') + '"' : '';
        return (
            '<svg xmlns="http://www.w3.org/2000/svg"' + cls + ' width="' + w + '" height="' + w + '" viewBox="0 0 48 48" fill="none" aria-hidden="true">' +
            '<path d="M24 9 A15 15 0 0 1 36.98 31.2 L24 24 Z" fill="currentColor" opacity="0.32"/>' +
            '<path d="M24 9 A15 15 0 0 1 36.98 31.2 L24 24 Z" fill="currentColor" opacity="0.48" transform="rotate(120 24 24)"/>' +
            '<path d="M24 9 A15 15 0 0 1 36.98 31.2 L24 24 Z" fill="currentColor" opacity="0.62" transform="rotate(240 24 24)"/>' +
            '<ellipse cx="24" cy="24.5" rx="6.2" ry="4.65" fill="currentColor" opacity="0.08" transform="rotate(-11 24 24.5)"/>' +
            '<circle cx="24" cy="24.5" r="2.35" fill="currentColor" opacity="0.85"/>' +
            '</svg>'
        );
    }

    function svgLoaderMark() {
        return (
            '<div class="so-loader-mark" aria-hidden="true">' +
            '<svg class="so-loader-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none">' +
            '<g class="so-loader-spin">' +
            '<path d="M24 9 A15 15 0 0 1 36.98 31.2 L24 24 Z" fill="#142a4a"/>' +
            '<path d="M24 9 A15 15 0 0 1 36.98 31.2 L24 24 Z" fill="#0d9488" transform="rotate(120 24 24)"/>' +
            '<path d="M24 9 A15 15 0 0 1 36.98 31.2 L24 24 Z" fill="#9dc9b8" transform="rotate(240 24 24)"/>' +
            '<ellipse cx="24" cy="24.5" rx="6.2" ry="4.65" fill="#ffffff" transform="rotate(-11 24 24.5)"/>' +
            '<circle cx="24" cy="24.5" r="2.35" fill="#0f172a"/>' +
            '<circle cx="22.6" cy="23.45" r="0.7" fill="#ffffff" opacity="0.92"/>' +
            '</g></svg></div>'
        );
    }

    function spinnerCompact() {
        return (
            '<div class="so-inline-loader" role="status" aria-live="polite">' +
            '<div class="so-loader" style="animation:none;padding:0;">' +
            svgLoaderMark() +
            '</div></div>'
        );
    }

    function loaderBlock(message, opts) {
        var msg = message != null && String(message).trim() !== '' ? String(message) : pickLoadingMessage();
        var showBar = !opts || opts.progress !== false;
        var bar = showBar ? '<div class="so-loader-track" aria-hidden="true"><div class="so-loader-bar"></div></div>' : '';
        return (
            '<div class="so-loader" role="status" aria-live="polite">' +
            svgLoaderMark() +
            '<p class="so-loader-caption">' + escapeHtml(msg) + '</p>' +
            bar +
            '</div>'
        );
    }

    function pickLoadingMessage() {
        var i = Math.floor(Math.random() * LOADING_MESSAGES.length);
        return LOADING_MESSAGES[i];
    }

    function escapeHtml(s) {
        if (typeof s !== 'string') return '';
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    function wordmarkHtml(tag, extraClass) {
        var t = tag || 'span';
        var ex = extraClass ? ' ' + String(extraClass).replace(/"/g, '') : '';
        return (
            '<' + t + ' class="sightops-wordmark' + ex + '">' +
            '<span class="sightops-wordmark-sight">Sight</span><span class="sightops-wordmark-ops">Ops</span>' +
            '</' + t + '>'
        );
    }

    var Brand = {
        APP_NAME: 'SightOps',
        TAGLINE: 'See more. Operate better.',
        SUBTITLE: 'Operational intelligence for multi-branch inventory',
        DEFAULT_COMPANY_LABEL: 'SightOps',
        POWERED_BY_LINE: 'Powered by SightOps',
        RECEIPT_FOOTER: 'Powered by SightOps',
        LOADING_MESSAGES: LOADING_MESSAGES,
        pickLoadingMessage: pickLoadingMessage,
        svgIconMark: svgIconMark,
        svgIconMarkMono: svgIconMarkMono,
        svgLoaderMark: svgLoaderMark,
        loaderBlock: loaderBlock,
        spinnerCompact: spinnerCompact,
        wordmarkHtml: wordmarkHtml,
    };

    global.SightOpsBrand = Brand;
})(typeof window !== 'undefined' ? window : this);
