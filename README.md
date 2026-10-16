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
    "upload_token": "public",
    "max_upload_gb": 10,
    "folders": [
        "D:\\shared",
        "E:\\shared",
        "\\\\nas\\media"
    ]
}
```

| Key             | Required | Default   | Description                                         |
|-----------------|----------|-----------|-----------------------------------------------------|
| `folders`       | yes      | -         | Ordered list of folders merged into one root        |
| `port`          | no       | `1122`    | TCP port to listen on                               |
| `host`          | no       | `0.0.0.0` | Interface to bind to (`127.0.0.1` = this PC only)   |
| `threads`       | no       | `8`       | Number of Waitress worker threads                   |
| `upload_token`  | no       | `public`  | Token required for uploads (`""` disables uploads)  |
| `max_upload_gb` | no       | `10`      | Maximum size of one uploaded archive, in GB         |

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

## Uploading zip archives

Anyone with the upload token can add data. Only `.zip` archives are
accepted. Each archive goes to the configured folder that currently has the
**most free space**.

* **Browser:** open `http://<server>:1122/_upload`, enter the token, pick a
  zip and choose whether to extract it.
* **Scripts:** `POST` the raw zip as the request body:

```bat
curl -H "X-Upload-Token: public" --data-binary @data.zip ^
     "http://<server>:1122/_upload?extract=1&name=data.zip"
```

```python
import requests
with open("data.zip", "rb") as f:
    r = requests.post("http://<server>:1122/_upload",
                      params={"extract": 0, "name": "data.zip"},
                      headers={"X-Upload-Token": "public"}, data=f)
print(r.status_code, r.json())
```

| Parameter | Meaning                                                    |
|-----------|------------------------------------------------------------|
| `extract` | `1` = extract into the folder root, `0` = store the zip as is |
| `name`    | File name of the archive (must end in `.zip`)              |
| token     | `X-Upload-Token` header (or `?token=` query parameter)     |

Behaviour:

* `extract=0`: the archive is stored as it is in the folder root. If an
  archive with the same name already exists in any folder, a short random
  suffix is added (`data_3fa9c1.zip`). The response shows the final name.
* `extract=1`: the contents are extracted into the root of the chosen
  folder. Folders with the same name are merged. Files with the same name are
  **overwritten**, and older copies in the other folders are removed so the
  new version is the one being served.
* Before extraction, the archive is checked for entries that would escape the
  folder (`../`, absolute paths) and for a total uncompressed size larger
  than the free space. Archives that fail either check are rejected.
* Uploads are staged in `upload_tmp/` in the repository folder and deleted
  after processing. That drive needs enough free space for the largest
  upload, roughly twice its size (Waitress buffers the request body first).
* The response is JSON. Errors use the matching HTTP status: 401 bad token,
  400 bad request or not a zip, 413 too large, 507 not enough free space.

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
