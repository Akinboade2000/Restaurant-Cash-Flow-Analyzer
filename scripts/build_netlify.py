import os
import re
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "frontend" / "templates"
STATIC = ROOT / "frontend" / "static"
OUTPUT = ROOT / "dist"
STATIC_REFERENCE = re.compile(
    r"\{\{\s*url_for\('static',\s*filename='([^']+)'\)\s*\}\}"
)


def main():
    api_url = os.environ.get("VERCEL_API_URL", "").strip().rstrip("/")
    parsed_url = urlparse(api_url)
    if (
        parsed_url.scheme != "https"
        or not parsed_url.netloc
        or parsed_url.path
        or parsed_url.query
        or parsed_url.fragment
        or parsed_url.username
    ):
        raise SystemExit(
            "Set VERCEL_API_URL to the HTTPS origin of your deployed Vercel API, "
            "for example https://your-api.vercel.app."
        )

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for source in STATIC.rglob("*"):
        destination = OUTPUT / "static" / source.relative_to(STATIC)
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())

    for template_name in ("index", "login", "register", "dashboard"):
        source = (TEMPLATES / f"{template_name}.html").read_text(encoding="utf-8")
        rendered, replacements = STATIC_REFERENCE.subn(
            lambda match: f"/static/{match.group(1)}",
            source,
        )
        if "{{ url_for(" in rendered:
            raise SystemExit(f"Unresolved Flask template reference in {template_name}.html.")
        if replacements == 0:
            raise SystemExit(f"No static asset references found in {template_name}.html.")
        (OUTPUT / f"{template_name}.html").write_text(rendered, encoding="utf-8")

    redirects = [
        f"/api/* {api_url}/api/:splat 200",
        "/dashboard /dashboard.html 200",
        "/login /login.html 200",
        "/register /register.html 200",
    ]
    (OUTPUT / "_redirects").write_text("\n".join(redirects) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
