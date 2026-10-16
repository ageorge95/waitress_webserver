"""
WSGI middleware that adds a zip upload endpoint in front of the static
file server.

    GET  /_upload                         -> small HTML upload page
    POST /_upload?extract=0|1&name=x.zip  -> raw zip archive in the body

The token is sent in the ``X-Upload-Token`` header (or ``?token=``).

The archive is first streamed into a temp folder next to the server, then
placed into the configured folder that currently has the most free space:

    * extract=0 -> the archive is moved there as-is. If a file with the same
      name already exists in any folder, a short random suffix is appended.
    * extract=1 -> the archive is extracted into the root of that folder.
      Folders merge, existing files are overwritten (copies of the same file
      in the other folders are removed so the new version is the one served).

The temp archive is always deleted afterwards.
"""
import hmac
import json
import logging
import os
import secrets
import shutil
import tempfile
import threading
import urllib.parse
import zipfile

from static_wsgi_app import StaticFileWSGIApp

UPLOAD_PATH = "/_upload"

log = logging.getLogger("upload")


class UploadError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class UploadWSGIMiddleware:
    chunk_size = 1024 * 1024

    def __init__(self, app, root_dirs, token, tmp_dir, max_bytes):
        self.app = app
        self.root_dirs = [os.path.abspath(d) for d in root_dirs]
        self.token = token
        self.tmp_dir = tmp_dir
        self.max_bytes = max_bytes
        # Serialises "pick folder + write" so concurrent uploads don't both
        # count on the same free space.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # WSGI entry point
    # ------------------------------------------------------------------ #
    def __call__(self, environ, start_response):
        if environ.get("PATH_INFO", "").rstrip("/") != UPLOAD_PATH:
            return self.app(environ, start_response)

        method = environ.get("REQUEST_METHOD", "GET").upper()
        if method in ("GET", "HEAD"):
            return self._page(start_response, method)
        if method != "POST":
            return self._json(start_response, "405 Method Not Allowed",
                              {"error": "use GET or POST"}, [("Allow", "GET, HEAD, POST")])

        try:
            result = self._handle_upload(environ)
        except UploadError as exc:
            return self._json(start_response, exc.status, {"error": str(exc)})
        except Exception:
            log.exception("Upload failed")
            return self._json(start_response, "500 Internal Server Error",
                              {"error": "internal error, see server log"})
        return self._json(start_response, "200 OK", result)

    # ------------------------------------------------------------------ #
    # Upload handling
    # ------------------------------------------------------------------ #
    def _handle_upload(self, environ):
        query = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))

        def param(key):
            values = query.get(key)
            return values[0] if values else ""

        if not self.token:
            raise UploadError("403 Forbidden", "uploads are disabled on this server")
        token = environ.get("HTTP_X_UPLOAD_TOKEN") or param("token")
        if not hmac.compare_digest(token.encode("utf-8"), self.token.encode("utf-8")):
            raise UploadError("401 Unauthorized", "invalid or missing upload token")

        extract = param("extract")
        if extract not in ("0", "1"):
            raise UploadError("400 Bad Request", "'extract' must be 0 or 1")

        name = os.path.basename(param("name").replace("\\", "/")).strip()
        if not name.lower().endswith(".zip") or len(name) <= 4:
            raise UploadError("400 Bad Request", "'name' must be a .zip file name")

        try:
            length = int(environ.get("CONTENT_LENGTH") or "")
        except ValueError:
            raise UploadError("411 Length Required", "Content-Length header is required")
        if length <= 0:
            raise UploadError("400 Bad Request", "empty upload")
        if length > self.max_bytes:
            raise UploadError("413 Payload Too Large",
                              f"upload exceeds the limit of {self.max_bytes} bytes")

        os.makedirs(self.tmp_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(suffix=".zip", dir=self.tmp_dir)
        try:
            with os.fdopen(fd, "wb") as out:
                self._copy_body(environ["wsgi.input"], out, length)
            if not zipfile.is_zipfile(tmp_path):
                raise UploadError("400 Bad Request", "the upload is not a valid zip archive")
            with self._lock:
                if extract == "1":
                    return self._extract(tmp_path, name)
                return self._store(tmp_path, name)
        finally:
            try:
                os.remove(tmp_path)
            except FileNotFoundError:
                pass

    def _copy_body(self, stream, out, length):
        remaining = length
        while remaining > 0:
            chunk = stream.read(min(self.chunk_size, remaining))
            if not chunk:
                raise UploadError("400 Bad Request", "upload ended before Content-Length bytes")
            out.write(chunk)
            remaining -= len(chunk)

    def _pick_folder(self, needed):
        best, best_free = None, -1
        for root in self.root_dirs:
            if not os.path.isdir(root):
                continue
            try:
                free = shutil.disk_usage(root).free
            except OSError:
                continue
            if free > best_free:
                best, best_free = root, free
        if best is None:
            raise UploadError("503 Service Unavailable", "no configured folder is currently available")
        if best_free < needed:
            raise UploadError("507 Insufficient Storage",
                              f"not enough free space: need {needed} bytes, largest free is {best_free}")
        return best

    def _store(self, tmp_path, name):
        dest_root = self._pick_folder(os.path.getsize(tmp_path))

        final = name
        while any(os.path.exists(os.path.join(root, final)) for root in self.root_dirs):
            final = f"{name[:-4]}_{secrets.token_hex(3)}.zip"

        dest = os.path.join(dest_root, final)
        # Copy under a temporary name first so a half-copied archive is never
        # mistaken for a complete one.
        shutil.move(tmp_path, dest + ".part")
        os.replace(dest + ".part", dest)
        log.info("Stored archive %s", dest)
        return {"status": "ok", "extracted": False, "name": final,
                "url": "/" + urllib.parse.quote(final)}

    def _extract(self, tmp_path, name):
        with zipfile.ZipFile(tmp_path) as zf:
            members = zf.infolist()
            # Zip bomb guard: declared sizes must fit in the free space
            # (zipfile itself refuses to output more than the declared size).
            dest_root = self._pick_folder(sum(m.file_size for m in members))
            # Zip slip guard: refuse entries that would land outside the folder.
            for m in members:
                target = os.path.abspath(os.path.join(dest_root, m.filename))
                if not StaticFileWSGIApp._is_inside(dest_root, target):
                    raise UploadError("400 Bad Request", f"archive contains an unsafe path: {m.filename}")
            zf.extractall(dest_root)

        # Overwrite semantics across the merged tree: remove other copies of
        # the extracted files so the new version is the one being served.
        files = [m.filename for m in members if not m.is_dir()]
        replaced = 0
        for root in self.root_dirs:
            if os.path.normcase(root) == os.path.normcase(dest_root):
                continue
            for rel in files:
                other = os.path.join(root, rel)
                if os.path.isfile(other):
                    os.remove(other)
                    replaced += 1

        log.info("Extracted %s (%d files) into %s, removed %d older copies elsewhere",
                 name, len(files), dest_root, replaced)
        return {"status": "ok", "extracted": True, "name": name,
                "files": len(files), "replaced_in_other_folders": replaced}

    # ------------------------------------------------------------------ #
    # Responses
    # ------------------------------------------------------------------ #
    @staticmethod
    def _json(start_response, status, payload, extra_headers=None):
        body = json.dumps(payload).encode("utf-8")
        headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
        if extra_headers:
            headers.extend(extra_headers)
        start_response(status, headers)
        return [body]

    @staticmethod
    def _page(start_response, method):
        body = UPLOAD_PAGE.encode("utf-8")
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"),
                                  ("Content-Length", str(len(body)))])
        return [b""] if method == "HEAD" else [body]


UPLOAD_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Upload zip archive</title>
<style>
body { font-family: sans-serif; max-width: 40em; margin: 2em auto; }
label { display: block; margin: .8em 0; }
progress { width: 100%; }
</style>
</head>
<body>
<h1>Upload zip archive</h1>
<form id="form">
<label>Token: <input type="password" id="token" required></label>
<label>Archive: <input type="file" id="file" accept=".zip,application/zip" required></label>
<label><input type="checkbox" id="extract"> Extract the archive</label>
<button type="submit" id="submit">Upload</button>
</form>
<progress id="bar" max="100" value="0" hidden></progress>
<pre id="out"></pre>
<p><a href="/">Back to files</a></p>
<script>
document.getElementById("form").onsubmit = function (e) {
  e.preventDefault();
  var file = document.getElementById("file").files[0];
  if (!file) return;
  var out = document.getElementById("out");
  var bar = document.getElementById("bar");
  var button = document.getElementById("submit");
  var extract = document.getElementById("extract").checked ? 1 : 0;
  var xhr = new XMLHttpRequest();
  xhr.open("POST", "/_upload?extract=" + extract + "&name=" + encodeURIComponent(file.name));
  xhr.setRequestHeader("X-Upload-Token", document.getElementById("token").value);
  xhr.upload.onprogress = function (ev) {
    if (!ev.lengthComputable) return;
    bar.value = ev.loaded / ev.total * 100;
    out.textContent = ev.loaded === ev.total
      ? "Upload complete, the server is processing the archive..."
      : "Uploading... " + Math.floor(bar.value) + "%";
  };
  xhr.onload = function () {
    button.disabled = false;
    var text = xhr.responseText;
    try { text = JSON.stringify(JSON.parse(text), null, 2); } catch (err) {}
    out.textContent = (xhr.status === 200 ? "Done" : "Failed (HTTP " + xhr.status + ")") + "\\n" + text;
  };
  xhr.onerror = function () { button.disabled = false; out.textContent = "Network error"; };
  button.disabled = true;
  bar.hidden = false;
  bar.value = 0;
  xhr.send(file);
};
</script>
</body>
</html>
"""
