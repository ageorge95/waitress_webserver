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

## Default behaviour

* Default port: **1122** (matches the previous `python -m http.server 1122`
  setup)
* Default host: `0.0.0.0` (reachable from other machines on the network, not
  just `localhost`)
* Default served folder: `www/` next to `server.py` (created automatically
  the first time you start the server if it doesn't exist yet)

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

This activates the virtual environment and runs `server.py` with the
defaults described above. Drop the files you want to share into the `www`
folder (or point the server at any other folder, see below) and browse to:

```
http://<this-computer-name-or-ip>:1122/
```

> **Tip:** Windows Firewall may prompt to allow Python/Waitress through on
> first start - accept it (at least for private networks) so colleagues on
> the same network can reach port 1122.

## Custom directory / port / host

`server.py` accepts arguments in the same style as `python -m http.server`:

```
python server.py [port] [-d DIRECTORY] [-b HOST] [-t THREADS]
```

| Argument              | Default                  | Description                              |
|-----------------------|---------------------------|-------------------------------------------|
| `port` (positional)   | `1122`                    | TCP port to listen on                     |
| `-d`, `--directory`   | `www` folder next to `server.py` | Folder whose contents get served   |
| `-b`, `--bind`        | `0.0.0.0`                 | Host/interface to bind to                 |
| `-t`, `--threads`     | `8`                       | Number of Waitress worker threads         |

Examples:

```bat
:: Serve C:\shared on the default port 1122
python server.py -d C:\shared

:: Serve the default www folder on port 8080
python server.py 8080

:: Bind only to localhost and use 16 worker threads
python server.py -b 127.0.0.1 -t 16
```

You can also just edit `START_server.bat` and append the arguments you want
after `python server.py`, or pass them straight to the batch file itself
(e.g. `START_server.bat 8080 -d C:\shared`), since it forwards all of its
arguments through.