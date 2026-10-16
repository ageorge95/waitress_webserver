# waitress_webserver

A tiny, production-grade replacement for `python -m http.server`, powered by
[Waitress](https://docs.pylonsproject.org/projects/waitress/) - a pure-Python,
multi-threaded WSGI server suitable for serving several users at the same
time.

It serves static files from a directory and generates a directory listing
when no `index.html` / `index.htm` is present, guessing the correct
`Content-Type` for every file - just like `python -m http.server` - but can
comfortably handle multiple concurrent colleagues browsing/downloading at
once thanks to Waitress's worker-thread pool.

Several folders (e.g. on different HDDs) can be merged into a **single
virtual root**: visitors see one tree and never know on which disk a file is
actually stored.

## Configuration (`config.json`)

All settings live in `config.json` in the repository root. The server
**refuses to start** if the file is missing or invalid.

```json
{
    "host": "0.0.0.0",
    "port": 1122,
    "threads": 8,
    "folders": [
        "D:\\shared",
        "E:\\shared",
        "\\\\nas\\media"
    ]
}
```

| Key       | Required | Default   | Description                                         |
|-----------|----------|-----------|-----------------------------------------------------|
| `folders` | yes      | -         | Ordered list of folders merged into one root        |
| `port`    | no       | `1122`    | TCP port to listen on                               |
| `host`    | no       | `0.0.0.0` | Interface to bind to (`127.0.0.1` = this PC only)   |
| `threads` | no       | `8`       | Number of Waitress worker threads                   |

Notes on `folders`:

* Backslashes must be doubled in JSON (`"D:\\shared"`), or use forward
  slashes (`"D:/shared"`).
* Relative paths are resolved against the repository root. `%VAR%` and `~`
  are expanded.
* **Order matters - first folder wins.** If the same file path exists in
  several folders, the copy from the folder listed first is served and the
  others are hidden.
* Sub-folders with the same name are **merged**: `D:\shared\music` and
  `E:\shared\music` both show up together under `/music/`.
* A folder that doesn't exist at startup only produces a **warning**. It is
  checked again on every request, so a disk that is plugged in later is
  served automatically without restarting.

## Installation

Run `Install.bat` once. It will:

1. Create a local virtual environment in `venv/`
2. Verify your Python version is compatible (Python 3.7+)
3. Install the dependencies from `requirements.txt` (just `waitress`)

```bat
Install.bat
```

Optionally pass a specific python executable/launcher as the first argument,
e.g. `Install.bat py`.

## Starting the server

```bat
START_server.bat
```

This activates the virtual environment and runs `server.py` using the
settings from `config.json`. Then browse to:

```
http://<this-computer-name-or-ip>:1122/
```

> **Tip:** Windows Firewall may prompt to allow Python/Waitress through on
> first start - accept it (at least for private networks) so colleagues on
> the same network can reach port 1122.
