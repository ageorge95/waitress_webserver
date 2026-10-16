import argparse
import logging
import os
import sys
from waitress import serve
from static_wsgi_app import StaticFileWSGIApp

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIRECTORY = os.path.join(SCRIPT_DIR, "www")
DEFAULT_PORT = 1122
DEFAULT_HOST = "0.0.0.0"
DEFAULT_THREADS = 8

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Serve a directory of static files using Waitress - a "
            "production-quality, multi-threaded WSGI server. Drop-in "
            "replacement for 'python -m http.server' that can comfortably "
            "handle several colleagues browsing/downloading at once."
        )
    )
    parser.add_argument(
        "port",
        nargs="?",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "-d", "--directory",
        default=None,
        help=(
            "Directory to serve (default: the 'www' folder next to "
            "server.py, created automatically on first run)"
        ),
    )
    parser.add_argument(
        "-b", "--bind",
        dest="host",
        default=DEFAULT_HOST,
        help=f"Host/interface to bind to (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "-t", "--threads",
        type=int,
        default=DEFAULT_THREADS,
        help=f"Number of Waitress worker threads (default: {DEFAULT_THREADS})",
    )
    return parser.parse_args()

def resolve_serve_directory(args):
    if args.directory is None:
        serve_dir = DEFAULT_DIRECTORY
        if not os.path.isdir(serve_dir):
            os.makedirs(serve_dir, exist_ok=True)
            print(f"Created default content directory: {serve_dir}")
    else:
        serve_dir = os.path.abspath(args.directory)

    if not os.path.isdir(serve_dir):
        print(f"ERROR: directory not found: {serve_dir}", file=sys.stderr)
        sys.exit(1)

    return serve_dir

def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stdout
    )
    logging.getLogger('waitress').setLevel(logging.INFO)

    serve_dir = resolve_serve_directory(args)
    application = StaticFileWSGIApp(serve_dir)

    print("=" * 60)
    print("Waitress static file server starting")
    print(f"  Serving directory : {serve_dir}")
    print(f"  Listening on      : http://{args.host}:{args.port}")
    print(f"  Worker threads    : {args.threads}")
    print("=" * 60)

    serve(application, host=args.host, port=args.port, threads=args.threads)

if __name__ == "__main__":
    main()