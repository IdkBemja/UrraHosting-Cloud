/* Resumable upload client (Fase 2). Files under CHUNK_THRESHOLD bytes use
 * the plain form submit already wired in browse.html (simplest path,
 * one request). Anything bigger is split into CHUNK_SIZE pieces and
 * POSTed one at a time to /drive/upload-chunk, so a dropped connection
 * only costs the current chunk - see
 * app/blueprints/drive/chunked_upload.py for the server side contract.
 */
(function () {
  const CHUNK_SIZE = 8 * 1024 * 1024;
  const CHUNK_THRESHOLD = 20 * 1024 * 1024;

  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]').content;
  }

  async function uploadChunked(file, parentId, onProgress) {
    const uploadId = crypto.randomUUID();
    const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

    for (let index = 0; index < totalChunks; index++) {
      const start = index * CHUNK_SIZE;
      const chunk = file.slice(start, start + CHUNK_SIZE);

      const body = new FormData();
      body.append("upload_id", uploadId);
      body.append("chunk_index", String(index));
      body.append("total_chunks", String(totalChunks));
      body.append("parent_id", parentId);
      body.append("filename", file.name);
      body.append("chunk", chunk);

      const response = await fetch("/drive/upload-chunk", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken() },
        body,
      });
      if (!response.ok) {
        throw new Error("Fallo al subir el fragmento " + index);
      }
      onProgress((index + 1) / totalChunks);
    }
  }

  function initChunkedUpload(formSelector) {
    const form = document.querySelector(formSelector);
    if (!form) return;
    const input = form.querySelector('input[type="file"]');
    const parentId = form.dataset.parentId;

    input.addEventListener("change", async () => {
      const file = input.files[0];
      if (!file || file.size < CHUNK_THRESHOLD) {
        form.requestSubmit(); // small file: normal single-request upload
        return;
      }
      try {
        await uploadChunked(file, parentId, (fraction) => {
          console.log("Subiendo " + file.name + ": " + Math.round(fraction * 100) + "%");
        });
        window.location.reload();
      } catch (err) {
        alert("Error subiendo el archivo: " + err.message);
      }
    });
  }

  // Auto-init on DOMContentLoaded instead of requiring an inline
  // <script>initChunkedUpload(...)</script> call in templates - the CSP
  // here is `script-src 'self'` with no 'unsafe-inline', so any inline
  // script tag would just be silently blocked by the browser.
  document.addEventListener("DOMContentLoaded", () => initChunkedUpload("#upload-form"));
})();
