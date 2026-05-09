(function () {
    const renderTokens = new WeakMap();

    function renderShell(container, shellHtml) {
        if (!container) return 0;
        const nextToken = (renderTokens.get(container) || 0) + 1;
        renderTokens.set(container, nextToken);
        container.innerHTML = shellHtml;
        return nextToken;
    }

    function isCurrentRender(container, token) {
        if (!container) return false;
        return renderTokens.get(container) === token;
    }

    async function runInstantShellHydrate(options) {
        const opts = options || {};
        const container = opts.container;
        const shellHtml = opts.shellHtml || "";
        const hydrate = typeof opts.hydrate === "function" ? opts.hydrate : async function () {};
        const onError = typeof opts.onError === "function" ? opts.onError : null;

        const token = renderShell(container, shellHtml);
        try {
            await hydrate({
                token: token,
                isCurrent: function () {
                    return isCurrentRender(container, token);
                },
            });
        } catch (error) {
            if (onError && isCurrentRender(container, token)) {
                onError(error);
            } else {
                throw error;
            }
        }
        return token;
    }

    function debounce(fn, waitMs) {
        let timer = null;
        const wait = Number.isFinite(waitMs) ? waitMs : 250;
        return function debounced() {
            const ctx = this;
            const args = arguments;
            if (timer) clearTimeout(timer);
            timer = setTimeout(function () {
                fn.apply(ctx, args);
            }, wait);
        };
    }

    window.WorkstationUX = {
        renderShell: renderShell,
        runInstantShellHydrate: runInstantShellHydrate,
        debounce: debounce,
        isCurrentRender: isCurrentRender,
    };
})();
