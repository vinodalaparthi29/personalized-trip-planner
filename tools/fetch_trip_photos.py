"""Download the photos an itinerary asks for from Wikipedia / Wikimedia Commons.

Usage:
    python tools/fetch_trip_photos.py .tmp/<trip_slug>

Reads the photo titles in itinerary.json (cover_photo, days[].photos, food[].photo), saves cropped JPEGs to
.tmp/<trip_slug>/photos/ and writes photos.json for render_trip_pdf.py. No API key is needed.

Each title is looked up as an exact Wikipedia article and uses its freely licensed lead image. If there isn't
one, Commons is searched, and a file counts only if the title's words appear in its filename. Prints one line
per title so a wrong match can be spotted without opening images. Photos are optional: a photo that can't be
found, or a Wikimedia failure, is reported and the exit code is still 0, so a trip is never blocked by this.
"""

import hashlib
import html
import io
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from PIL import Image, ImageOps

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "PersonalTripPlanner/1.0 (personal travel PDF tool; python-requests)"}

REQUEST_GAP = 2.0  # seconds between requests; Wikimedia answers 429 after about 10 quick ones
MAX_RETRIES = 3
MAX_RETRY_WAIT = 60  # give up on Wikimedia for this run rather than wait longer than this
BATCH_SIZE = 50  # most titles the API accepts in one request
THUMB_WIDTH = 960  # a standard Wikimedia thumbnail size
MIN_WIDTH = 800
CROP_RATIO = 3 / 2
JPEG_QUALITY = 72
NOT_A_PHOTO = re.compile(r"logo|map|flag|seal|coat[ _]of[ _]arms|emblem|icon|locator|diagram|banner", re.I)
IMAGE_INFO = {"prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": THUMB_WIDTH,
              "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|NonFree"}


class RateLimited(Exception):
    """Wikimedia kept refusing requests, so stop asking during this run."""


class Client:
    """Spaces out requests and honours Retry-After."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.last = 0.0

    def get(self, url, params=None):
        for _ in range(MAX_RETRIES):
            time.sleep(max(0.0, self.last + REQUEST_GAP - time.time()))
            self.last = time.time()
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code not in (429, 503):
                response.raise_for_status()
                return response
            wait = retry_after(response)
            if wait > MAX_RETRY_WAIT:
                raise RateLimited(f"asked to wait {wait}s")
            print(f"Wikimedia asked to wait {wait}s (HTTP {response.status_code}).", flush=True)
            time.sleep(wait)
        raise RateLimited(f"still refused after {MAX_RETRIES} tries")

    def query(self, url, **params):
        return self.get(url, {"action": "query", "format": "json", **params}).json().get("query") or {}


def retry_after(response):
    try:
        return max(1, int(response.headers.get("Retry-After", 30)))
    except ValueError:  # the header may also be an HTTP date
        return 30


def wanted_titles(it):
    """The photo titles in the itinerary, without duplicates, in the order they appear."""
    titles = [it.get("cover_photo")]
    for day in it.get("days", []):
        titles += day.get("photos") or []
    titles += [f.get("photo") for f in it.get("food", [])]
    return list(dict.fromkeys(t.strip() for t in titles if isinstance(t, str) and t.strip()))


def batches(items):
    return [items[i:i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]


def resolve_names(result, names):
    """Map each name we asked for to the name the API answered under (normalized, then redirected)."""
    steps = {}
    for key in ("normalized", "redirects"):
        steps[key] = {step["from"]: step["to"] for step in result.get(key, [])}
    resolved = {}
    for name in names:
        name_n = steps["normalized"].get(name, name)
        resolved[name] = steps["redirects"].get(name_n, name_n)
    return resolved


def lead_images(client, titles):
    """Return {title: image file name} for titles whose Wikipedia article has a free lead image."""
    found = {}
    for batch in batches([t for t in titles if "|" not in t]):
        result = client.query(WIKIPEDIA_API, titles="|".join(batch), prop="pageimages", piprop="original|name",
                              pilicense="free", redirects=1)
        pages = {page.get("title"): page for page in (result.get("pages") or {}).values()}
        for title, final in resolve_names(result, batch).items():
            page = pages.get(final) or {}
            width = (page.get("original") or {}).get("width") or 0
            name = page.get("pageimage")
            if name and width >= MIN_WIDTH and not NOT_A_PHOTO.search(name):
                found[title] = "File:" + name
    return found


def describe(page, via):
    """Turn an imageinfo result into a manifest entry, or None if we can't use or credit the file."""
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata") or {}
    licence = (meta.get("LicenseShortName") or {}).get("value")
    if not info.get("thumburl") or not licence or (meta.get("NonFree") or {}).get("value"):
        return None
    if info.get("mime") not in ("image/jpeg", "image/png") or info.get("width", 0) < MIN_WIDTH:
        return None
    return {
        "matched": page.get("title", "").removeprefix("File:"),
        "via": via,
        "author": clean_author((meta.get("Artist") or {}).get("value")),
        "licence": html.unescape(licence),
        "licence_url": (meta.get("LicenseUrl") or {}).get("value") or "",
        "source_url": info.get("descriptionurl") or "",
        "thumb_url": info["thumburl"],
    }


def clean_author(raw):
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw or "")).split())
    return text[:70] or "Wikimedia Commons"


def lead_image_details(client, lead):
    """Return {title: manifest entry} for the lead images found on Wikipedia."""
    details = {}
    for batch in batches(sorted(set(lead.values()))):
        result = client.query(WIKIPEDIA_API, titles="|".join(batch), **IMAGE_INFO)
        pages = {page.get("title"): page for page in (result.get("pages") or {}).values()}
        finals = resolve_names(result, batch)
        for title, name in lead.items():
            page = pages.get(finals.get(name))
            entry = describe(page, "wikipedia") if page else None
            if entry:
                details[title] = entry
    return details


def fold(text):
    """Lowercase ASCII, so 'Sensō-ji' matches 'Senso-ji' in a filename."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def key_words(title):
    words = re.findall(r"[a-z0-9]+", fold(re.sub(r"\(.*?\)", " ", title)))
    return [w for w in words if len(w) >= 3] or words


def search_commons(client, title):
    """Find a photo on Commons whose filename contains every key word of the title; prefer landscape ones."""
    result = client.query(COMMONS_API, generator="search", gsrsearch=f"{title} filetype:bitmap", gsrnamespace=6,
                          gsrlimit=10, **IMAGE_INFO)
    pages = sorted((result.get("pages") or {}).values(), key=lambda page: page.get("index", 0))
    words = key_words(title)
    candidates = []
    for page in pages:
        filename = fold(page.get("title", ""))
        if not words or not all(w in filename for w in words) or NOT_A_PHOTO.search(filename):
            continue
        entry = describe(page, "commons")
        if entry:
            info = page["imageinfo"][0]
            candidates.append((info.get("height", 0) > info.get("width", 0), entry))
    candidates.sort(key=lambda c: c[0])  # stable: landscape first, otherwise search order
    return candidates[0][1] if candidates else None


def save_photo(data, path):
    """Crop to the shared landscape shape and save as a JPEG the PDF can embed as is."""
    with Image.open(io.BytesIO(data)) as source:
        img = ImageOps.exif_transpose(source).convert("RGB")
    img = ImageOps.fit(img, (THUMB_WIDTH, round(THUMB_WIDTH / CROP_RATIO)), Image.Resampling.LANCZOS)
    img.save(path, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)


def file_name(title):
    slug = re.sub(r"[^a-z0-9]+", "_", fold(title)).strip("_")[:40]
    return f"{slug}_{hashlib.sha1(title.encode('utf-8')).hexdigest()[:8]}.jpg"


def fetch_all(titles, folder, manifest, write):
    """Fill manifest in place, saving after each photo, and return {title: reason} for the ones skipped."""
    client = Client()
    photo_dir = folder / "photos"
    photo_dir.mkdir(exist_ok=True)

    todo = [t for t in titles if t not in manifest]
    skipped = {}
    if not todo:
        return skipped
    try:
        details = lead_image_details(client, lead_images(client, todo))
        for title in todo:
            entry = details.get(title) or search_commons(client, title)
            if not entry:
                skipped[title] = "no usable free photo"
                continue
            try:
                data = client.get(entry["thumb_url"]).content
            except requests.HTTPError as e:  # one dead file shouldn't cost the other photos
                skipped[title] = f"download failed ({e.response.status_code})"
                continue
            try:
                save_photo(data, photo_dir / file_name(title))
            except (OSError, ValueError, Image.DecompressionBombError) as e:
                skipped[title] = f"unreadable image ({e})"
                continue
            del entry["thumb_url"]
            manifest[title] = {"file": file_name(title), **entry}
            write()
    except (RateLimited, requests.RequestException, ValueError) as e:
        print(f"WARNING: stopped fetching photos: {e}")
        for title in todo:
            if title not in manifest:
                skipped.setdefault(title, "not fetched (Wikimedia unavailable)")
    return skipped


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # titles like Sensō-ji under a Windows console
    folder = Path(sys.argv[1])
    try:
        it = json.loads((folder / "itinerary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"Could not read itinerary.json: {e}")
        sys.exit(1)

    manifest_path = folder / "photos.json"
    titles = wanted_titles(it)
    manifest = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError:
            print("WARNING: photos.json was unreadable; fetching again.")
    # Keep earlier downloads that are still wanted; forget the rest so a replaced title leaves the PDF.
    manifest = {t: e for t, e in manifest.items() if t in titles and (folder / "photos" / e.get("file", "?")).is_file()}

    def write():
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    write()
    if not titles:
        print("No photo titles in the itinerary.")
        return
    skipped = fetch_all(titles, folder, manifest, write)
    write()
    for title in titles:
        if title in manifest:
            print(f"{title} -> {manifest[title]['matched']} ({manifest[title]['via']})")
        else:
            print(f"{title} -> skipped: {skipped.get(title, 'not fetched')}")
    print(f"Photos: {len(manifest)} of {len(titles)} ready.")


if __name__ == "__main__":
    main()
