document.addEventListener("DOMContentLoaded", function () {
    const confirmForms = document.querySelectorAll("form[data-confirm]");
    confirmForms.forEach(function (form) {
        form.addEventListener("submit", function (event) {
            const message = form.getAttribute("data-confirm") || "Are you sure you want to proceed?";
            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });
});
