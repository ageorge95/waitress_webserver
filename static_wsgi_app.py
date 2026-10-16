"""
A minimal, dependency-free WSGI application that reproduces the behaviour of
Python's built-in ``python -m http.server``:

    * Serves static files from a root directory.
    * Generates an HTML directory listing when no ``index.html`` /
      ``index.htm`` is present (sorted alphabetically, case-insensitive).
    * Guesses the correct ``Content-Type`` for every file.
    * Redirects "directory" URLs that are missing a trailing slash.
    * Supports GET / HEAD and single-range ``Range`` requests (useful for
      resuming downloads or seeking within media files).
    * Blocks any attempt to escape the served root directory
      (directory-traversal protection).

It only depends on the Python standard library, so the only extra
requirement to actually expose it to the network is ``waitress`` itself.
"""
import html
import mimetypes
import os
import re
import urllib.parse
from datetime import datetime, timezone
from wsgiref.util import FileWrapper

# Make sure unknown extensions fall back to a sane binary type, same as
# http.server does.
mimetypes.init()
mimetypes.add_type("application/octet-stream", "")

class StaticFileWSGIApp:
    """A tiny static file server exposed as a WSGI callable."""

    index_files = ("index.html", "index.htm")
    chunk_size = 64 * 1024

    def __init__(self, root_dir="."):
        self.root_dir = os.path.abspath(root_dir)

    # ------------------------------------------------------------------ #
    # WSGI entry point
    # ------------------------------------------------------------------ #
    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET").upper()
        if method not in ("GET", "HEAD"):
            return self._error(start_response, "405 Method Not Allowed",
                                [("Allow", "GET, HEAD")])

        try:
            path = self._resolve_path(environ.get("PATH_INFO", "/"))
        except PermissionError:
            return self._error(start_response, "403 Forbidden")

        if path is None:
            return self._error(start_response, "404 Not Found")

        if os.path.isdir(path):
            index = self._find_index(path)
            if index:
                path = index
            else:
                return self._serve_directory_listing(environ, start_response, path)

        if not os.path.isfile(path):
            return self._error(start_response, "404 Not Found")

        return self._serve_file(environ, start_response, path, method)

    # ------------------------------------------------------------------ #
    # Path resolution / security
    # ------------------------------------------------------------------ #
    def _resolve_path(self, path_info):
        path_info = urllib.parse.unquote(path_info)
        # PATH_INFO always starts with '/' per the WSGI spec.
        relative_path = path_info.lstrip("/")
        normalized = os.path.normpath(relative_path)
        if normalized in (".", ""):
            normalized = ""

        full_path = os.path.abspath(os.path.join(self.root_dir, normalized))
        if full_path != self.root_dir and not full_path.startswith(self.root_dir + os.sep):
            # Someone tried to escape the served directory with e.g. '../..'
            raise PermissionError("Path traversal attempt blocked")

        if not os.path.exists(full_path):
            return None
        return full_path

    def _find_index(self, dir_path):
        for name in self.index_files:
            candidate = os.path.join(dir_path, name)
            if os.path.isfile(candidate):
                return candidate
        return None

    # ------------------------------------------------------------------ #
    # Directory listing
    # ------------------------------------------------------------------ #
    def _serve_directory_listing(self, environ, start_response, dir_path):
        request_path = environ.get("PATH_INFO", "/")
        if not request_path.endswith("/"):
            location = request_path + "/"
            query = environ.get("QUERY_STRING", "")
            if query:
                location += "?" + query
            start_response("301 Moved Permanently", [("Location", location), ("Content-Length", "0")])
            return [b""]

        try:
            entries = sorted(os.listdir(dir_path), key=str.lower)
        except OSError:
            return self._error(start_response, "403 Forbidden")

        display_path = html.escape(urllib.parse.unquote(request_path))
        rows = []
        if request_path != "/":
            rows.append('<li><a href="../">../</a></li>')

        for name in entries:
            full_entry = os.path.join(dir_path, name)
            display_name = name
            link_name = urllib.parse.quote(name)
            if os.path.isdir(full_entry):
                display_name += "/"
                link_name += "/"
            rows.append(f'<li><a href="{link_name}">{html.escape(display_name)}</a></li>')

        body = (
            "<!DOCTYPE html>\n<html>\n<head>\n"
            f'<meta charset="utf-8">\n<title>Directory listing for {display_path}</title>\n'
            "</head>\n<body>\n"
            f"<h1>Directory listing for {display_path}</h1>\n"
            "<hr>\n<ul>\n" + "\n".join(rows) + "\n</ul>\n<hr>\n</body>\n</html>\n"
        )
        encoded = body.encode("utf-8", "surrogateescape")
        headers = [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(encoded))),
        ]
        start_response("200 OK", headers)
        return [encoded]

    # ------------------------------------------------------------------ #
    # File serving (with basic Range support)
    # ------------------------------------------------------------------ #
    def _serve_file(self, environ, start_response, file_path, method):
        try:
            stat_result = os.stat(file_path)
        except OSError:
            return self._error(start_response, "404 Not Found")

        content_type, _encoding = mimetypes.guess_type(file_path)
        content_type = content_type or "application/octet-stream"
        file_size = stat_result.st_size
        last_modified = self._http_date(stat_result.st_mtime)

        start, end, status = self._parse_range(environ, file_size)
        headers = [
            ("Content-Type", content_type),
            ("Last-Modified", last_modified),
            ("Accept-Ranges", "bytes"),
        ]

        if status == "206 Partial Content":
            headers.append(("Content-Range", f"bytes {start}-{end}/{file_size}"))
            length = end - start + 1
        else:
            length = file_size
        headers.append(("Content-Length", str(length)))

        start_response(status, headers)

        if method == "HEAD":
            return [b""]

        file_obj = open(file_path, "rb")
        if status == "206 Partial Content":
            file_obj.seek(start)
            return _LimitedFileWrapper(file_obj, length, self.chunk_size)
        return FileWrapper(file_obj, self.chunk_size)

    @staticmethod
    def _parse_range(environ, file_size):
        no_range = (0, file_size - 1 if file_size else 0, "200 OK")
        range_header = environ.get("HTTP_RANGE")
        if not range_header:
            return no_range

        match = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not match:
            return no_range

        start_s, end_s = match.groups()
        if start_s == "" and end_s == "":
            return no_range

        if start_s == "":
            # Suffix range, e.g. "bytes=-500" -> last 500 bytes.
            suffix_length = int(end_s)
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else file_size - 1
            end = min(end, file_size - 1)

        if file_size == 0 or start > end or start >= file_size:
            return no_range

        return start, end, "206 Partial Content"

    @staticmethod
    def _http_date(timestamp):
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )

    # ------------------------------------------------------------------ #
    # Errors
    # ------------------------------------------------------------------ #
    @staticmethod
    def _error(start_response, status, extra_headers=None):
        body = f"<html><body><h1>{status}</h1></body></html>".encode("utf-8")
        headers = [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ]
        if extra_headers:
            headers.extend(extra_headers)
        start_response(status, headers)
        return [body]


class _LimitedFileWrapper:
    """Iterable file wrapper that stops after ``length`` bytes - used to
    serve HTTP Range ("206 Partial Content") responses."""

    def __init__(self, file_obj, length, block_size):
        self.file_obj = file_obj
        self.remaining = length
        self.block_size = block_size

    def __iter__(self):
        return self

    def __next__(self):
        if self.remaining <= 0:
            self.close()
            raise StopIteration
        chunk = self.file_obj.read(min(self.block_size, self.remaining))
        if not chunk:
            self.close()
            raise StopIteration
        self.remaining -= len(chunk)
        return chunk

    def close(self):
        self.file_obj.close()