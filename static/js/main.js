/* main.js — shared UI utilities */

// Close modal when clicking outside
document.addEventListener("click", function (e) {
  const overlay = document.getElementById("new-session-modal");
  if (overlay && e.target === overlay) {
    overlay.style.display = "none";
  }
});

// Fade-in page content on load
document.addEventListener("DOMContentLoaded", function () {
  document.body.style.opacity = "0";
  document.body.style.transition = "opacity 0.3s ease";
  requestAnimationFrame(function () {
    requestAnimationFrame(function () {
      document.body.style.opacity = "1";
    });
  });
});
