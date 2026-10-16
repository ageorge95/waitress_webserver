import json
import logging
import os
import sys
from waitress import serve
from static_wsgi_app import StaticFileWSGIApp

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

# Used when the corresponding key is absent from config.json.
DEFAULT_PORT = 1122
DEFAULT_HOST = "0.0.0.0"
DEFAULT_THREADS = 8

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

    return {"folders": resolved, "port": port, "host": host, "threads": threads}

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

    application = StaticFileWSGIApp(folders)

    print("=" * 60)
    print("Waitress static file server starting")
    print("  Serving folders (first match wins):")
    for i, folder in enumerate(folders, 1):
        status = "MISSING" if folder in missing else "ok"
        print(f"    {i}. [{status}] {folder}")
    print(f"  Listening on      : http://{config['host']}:{config['port']}")
    print(f"  Worker threads    : {config['threads']}")
    print("=" * 60)

    serve(application, host=config["host"], port=config["port"], threads=config["threads"])

if __name__ == "__main__":
    main()
