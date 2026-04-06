(function () {
    const root = document.documentElement;
    const storageKey = "quizy-theme";
    const savedTheme = localStorage.getItem(storageKey);

    if (savedTheme) {
        root.setAttribute("data-theme", savedTheme);
    }

    const toggle = document.getElementById("themeToggle");
    if (toggle) {
        toggle.addEventListener("click", function () {
            const current = root.getAttribute("data-theme") || "light";
            const next = current === "light" ? "dark" : "light";
            root.setAttribute("data-theme", next);
            localStorage.setItem(storageKey, next);
        });
    }

    const revealNodes = document.querySelectorAll(".reveal, .card-panel, .card-glass");
    if (!revealNodes.length) {
        return;
    }

    const observer = new IntersectionObserver(
        function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add("in-view");
                    observer.unobserve(entry.target);
                }
            });
        },
        { threshold: 0.12 }
    );

    revealNodes.forEach(function (node, index) {
        node.style.animationDelay = (index % 8) * 40 + "ms";
        observer.observe(node);
    });

    const progressNodes = document.querySelectorAll(".bar-fill[data-progress]");
    progressNodes.forEach(function (node) {
        const value = Number(node.getAttribute("data-progress") || "0");
        const clamped = Math.max(0, Math.min(100, value));
        node.style.width = `${clamped}%`;
    });
})();
