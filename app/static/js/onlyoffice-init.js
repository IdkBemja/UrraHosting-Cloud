/* Reads the editor config from the JSON <script> tag (data, not
 * executable script - CSP's script-src doesn't apply to it) instead of
 * inlining the config object directly into a <script> block, which
 * would be blocked by this app's CSP (script-src has no 'unsafe-inline').
 */
document.addEventListener("DOMContentLoaded", () => {
  const configEl = document.getElementById("editor-config");
  if (!configEl || typeof DocsAPI === "undefined") return;
  const config = JSON.parse(configEl.textContent);
  new DocsAPI.DocEditor("editor-placeholder", config);
});
