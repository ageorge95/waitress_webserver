import json
import logging
import os
import shutil
import sys
import tempfile
from waitress import serve
from static_wsgi_app import StaticFileWSGIApp
from upload_wsgi_app import UPLOAD_PATH, UploadWSGIMiddleware

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
# Uploaded archives are staged here before being moved to a served folder.
UPLOAD_TMP_DIR = os.path.join(SCRIPT_DIR, "upload_tmp")

# Used when the corresponding key is absent from config.json.
DEFAULT_PORT = 1122
DEFAULT_HOST = "0.0.0.0"
DEFAULT_THREADS = 8
DEFAULT_UPLOAD_TOKEN = "public"
DEFAULT_MAX_UPLOAD_GB = 10

class ConfigError(Exception):
    pass

def load_config(path=CONFIG_PATH):
    """Load and validate config.json. Raises ConfigError on any problem."""
    if not os.path.isfile(path):
        raise ConfigError(f"configuration file not found: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("the top level of config.json must be a JSON object")

    folders = raw.get("folders")
    if not isinstance(folders, list) or not folders:
        raise ConfigError("'folders' must be a non-empty list of folder paths")
    if not all(isinstance(f, str) and f.strip() for f in folders):
        raise ConfigError("every entry in 'folders' must be a non-empty string")

    port = raw.get("port", DEFAULT_PORT)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigError("'port' must be an integer between 1 and 65535")

    host = raw.get("host", DEFAULT_HOST)
    if not isinstance(host, str) or not host.strip():
        raise ConfigError("'host' must be a non-empty string")

    threads = raw.get("threads", DEFAULT_THREADS)
    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
        raise ConfigError("'threads' must be a positive integer")

    upload_token = raw.get("upload_token", DEFAULT_UPLOAD_TOKEN)
    if not isinstance(upload_token, str):
        raise ConfigError("'upload_token' must be a string (empty string disables uploads)")

    max_upload_gb = raw.get("max_upload_gb", DEFAULT_MAX_UPLOAD_GB)
    if isinstance(max_upload_gb, bool) or not isinstance(max_upload_gb, (int, float)) or max_upload_gb <= 0:
        raise ConfigError("'max_upload_gb' must be a positive number")

    # Relative folder paths are resolved against the repo root (not the
    # current working directory) so behaviour doesn't depend on where the
    # server is launched from. Duplicates are dropped, keeping the first.
    resolved = []
    seen = set()
    for folder in folders:
        expanded = os.path.expandvars(os.path.expanduser(folder.strip()))
        full = os.path.abspath(os.path.join(SCRIPT_DIR, expanded))
        key = os.path.normcase(full)
        if key not in seen:
            seen.add(key)
            resolved.append(full)

    return {"folders": resolved, "port": port, "host": host, "threads": threads,
            "upload_token": upload_token.strip(),
            "max_upload_bytes": int(max_upload_gb * 1024 ** 3)}

def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stdout
    )
    logging.getLogger('waitress').setLevel(logging.INFO)
    log = logging.getLogger("server")

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("See README.md for the expected config.json format.", file=sys.stderr)
        sys.exit(1)

    folders = config["folders"]
    missing = [f for f in folders if not os.path.isdir(f)]
    for folder in missing:
        log.warning("Configured folder not found (skipped until it becomes available): %s", folder)
    if len(missing) == len(folders):
        log.warning("None of the configured folders currently exist - every request will return 404")

    # Waitress buffers large request bodies in temp files before the app
    # sees them; keep those next to the server (not in %TEMP%) as well.
    # Leftovers from a previous crash are cleared on startup.
    shutil.rmtree(UPLOAD_TMP_DIR, ignore_errors=True)
    os.makedirs(UPLOAD_TMP_DIR, exist_ok=True)
    tempfile.tempdir = UPLOAD_TMP_DIR

    application = UploadWSGIMiddleware(
        StaticFileWSGIApp(folders),
        folders,
        token=config["upload_token"],
        tmp_dir=UPLOAD_TMP_DIR,
        max_bytes=config["max_upload_bytes"],
    )

    print("=" * 60)
    print("Waitress static file server starting")
    print("  Serving folders (first match wins):")
    for i, folder in enumerate(folders, 1):
        status = "MISSING" if folder in missing else "ok"
        print(f"    {i}. [{status}] {folder}")
    print(f"  Listening on      : http://{config['host']}:{config['port']}")
    print(f"  Worker threads    : {config['threads']}")
    if config["upload_token"]:
        print(f"  Upload page       : http://{config['host']}:{config['port']}{UPLOAD_PATH}")
        print(f"  Max upload size   : {config['max_upload_bytes'] / 1024 ** 3:g} GB")
    else:
        print("  Uploads           : disabled (empty upload_token)")
    print("=" * 60)

    serve(application, host=config["host"], port=config["port"], threads=config["threads"],
          max_request_body_size=config["max_upload_bytes"])

if __name__ == "__main__":
    main()
