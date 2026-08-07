/* Unobtrusive replacement for inline `onsubmit="return confirm(...)"`
 * attributes, which are inline event handlers and get silently blocked
 * by this app's CSP (`script-src 'self'`, no 'unsafe-inline') - without
 * this, those forms would submit immediately with no confirmation
 * prompt at all instead of throwing a visible error, which is worse.
 * Usage: <form data-confirm="Seguro?"> ... </form>
 */
document.addEventListener("submit", (event) => {
  const message = event.target.getAttribute && event.target.getAttribute("data-confirm");
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});
