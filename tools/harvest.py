#!/usr/bin/env python3
"""Build a thumbnail set from ScreenScraper, to host beside libretro's.

libretro has no Named_Logos for Game Boy Color at all — the folder does not exist — so every GBC
cart falls back to a hand-dropped logo. ScreenScraper has a clear logo (`wheel`) for most of
them, under CC BY-NC-SA 4.0: redistributable with attribution, as long as the set that results
carries the same licence.

It also records each cart's `look`: the ground colour and edge band of its printed label, measured
from ScreenScraper's scan of the cartridge as it downloads. Only the measurements are kept, in
index.json; the scan is never saved. Measuring needs Pillow and numpy; a run of `--media wheel`
alone does not.

This runs locally. Credentials come from the environment, the images land in a folder you push to
a repository of your own, and the studio only ever fetches the result over https. None of the CORS
and credential problems that rule ScreenScraper out of the page itself apply here.

    SS_DEVID=... SS_DEVPASSWORD=... SS_SSID=... SS_SSPASSWORD=... \\
        tools/harvest.py --probe "../slot/sdcard/Games/GBC/Pokemon - Crystal Version.gbc"

    SS_... tools/harvest.py --card ../slot/sdcard --out ../slot-thumbnails
    SS_... tools/harvest.py --dat all --out ../slot-thumbnails

Alongside the images it writes index.json, mapping CRC32 to the file that was saved. The studio
already computes a cart's CRC32, so that index is an exact lookup: no name matching, no probing a
url per cart to see whether it 404s, and it reaches roms No-Intro has never heard of.

Files are named by that CRC32 rather than by a game's name, so nothing in the set is named after a
database it did not come from. The No-Intro dat is read only to know which dumps exist and what to
call them while the run reports itself; every image is ScreenScraper's.

ScreenScraper's quota is per account, per minute and per day, and their documentation makes
managing it the client's job rather than the server's. This reads the account's own limits before
it starts and stops when the day's allowance is gone, leaving what it has written in place: a
later run skips whatever is already on disk, so a set is built across as many days as it needs.
"""

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = 'https://api.screenscraper.fr/api2'
DAT = 'https://raw.githubusercontent.com/libretro/libretro-database/master/metadat/no-intro/'

# The card folders slot files roms under, and libretro's name for each system. The ScreenScraper
# system id is looked up from that name rather than hard-coded, so a renumbering upstream cannot
# quietly harvest the wrong console's art.
PLATFORMS = {
    'GBA': 'Nintendo - Game Boy Advance',
    'GB': 'Nintendo - Game Boy',
    'GBC': 'Nintendo - Game Boy Color',
    'SNES': 'Nintendo - Super Nintendo Entertainment System',
}
EXTENSIONS = {'GBA': ('.gba',), 'GB': ('.gb', '.gbc'), 'GBC': ('.gb', '.gbc'), 'SNES': ('.sfc', '.smc')}

# ScreenScraper's own system ids. They are named "Game Boy Color", not libretro's "Nintendo -
# Game Boy Color", so there is no shared name to look them up by. Stated here and then checked
# against the live list at startup: a renumbering upstream would otherwise file one console's art
# under another's name, silently and for the whole run.
SS_SYSTEM = {'GB': 9, 'GBC': 10, 'GBA': 12, 'SNES': 4}
SS_EXPECT = {'GB': 'game boy', 'GBC': 'game boy color', 'GBA': 'game boy advance', 'SNES': 'super nintendo'}

# Where each media lands, in the layout libretro uses and the studio already fetches.
# A media's own name is its folder: <platform>/<media type>/<crc>.png. The platform folders are
# the ones slot files roms under, so the set speaks the card's vocabulary, and the media folders
# are ScreenScraper's own type names, so another type needs no table here to be harvested.

# Most dumps in circulation are USA or World, so prefer the art that belongs with those before
# falling back to whatever a game has.
REGIONS = ('us', 'wor', 'eu', 'jp')
COUNTRY = {
    'USA': 'us', 'World': 'wor', 'Europe': 'eu', 'Japan': 'jp', 'Germany': 'de', 'France': 'fr',
    'Spain': 'sp', 'Italy': 'it', 'UK': 'uk', 'Australia': 'au', 'Netherlands': 'nl',
    'Sweden': 'se', 'Korea': 'kr', 'Brazil': 'br', 'China': 'cn',
}
IN_EUROPE = {'de', 'fr', 'sp', 'it', 'uk', 'au', 'nl', 'se'}


def regions_for(name):
    found = re.search(r'\(([^)]*)\)', name)
    own = COUNTRY.get(found.group(1).split(',')[0].strip()) if found else None
    first = [own] + (['eu'] if own in IN_EUROPE else []) if own else []
    return tuple(dict.fromkeys(first + list(REGIONS)))


# Credentials can sit in a .env file at the repository's root (or the folder the command runs
# from) instead of being exported by hand. .gitignore refuses .env, so they cannot be committed.
ENV_FILES = (Path.cwd() / '.env', Path(__file__).resolve().parent.parent / '.env')


def parse_env(text):
    """KEY=VALUE per line; `export ` in front, quotes around the value, blank lines and # comments
    are all allowed, so the same file can also be `source`d by a shell."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].lstrip()
        key, sep, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not sep or not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '\'"':
            value = value[1:-1]
        else:
            value = value.split(' #', 1)[0].rstrip()
        out[key] = value
    return out


def load_env(paths=ENV_FILES):
    """Fill the environment from the first .env found. A variable already set wins, so a one-off
    `SS_SSID=other tools/scrape.py ...` still overrides the file."""
    for path in dict.fromkeys(paths):
        if path.is_file():
            for key, value in parse_env(path.read_text()).items():
                os.environ.setdefault(key, value)
            return path
    return None


def creds():
    load_env()
    missing = [k for k in ('SS_DEVID', 'SS_DEVPASSWORD') if not os.environ.get(k)]
    if missing:
        sys.exit(f'set {" and ".join(missing)} in .env at the repository root (see .env.example) '
                 'or in the environment')
    c = {
        'devid': os.environ['SS_DEVID'],
        'devpassword': os.environ['SS_DEVPASSWORD'],
        'softname': os.environ.get('SS_SOFTNAME', 'slot-cart-studio'),
        'output': 'json',
    }
    # A user account carries the quota; without one the per-day allowance is too small to build
    # anything but a handful of files.
    if os.environ.get('SS_SSID'):
        c['ssid'] = os.environ['SS_SSID']
        c['sspassword'] = os.environ.get('SS_SSPASSWORD', '')
    return c


class QuotaSpent(Exception):
    pass


class Refused(Exception):
    """ScreenScraper turned the run away as a whole: credentials wrong, the API closed or
    overloaded, or the software blocked. Retrying would only add load, so the run stops."""


# ScreenScraper's own answers, from its API documentation. 404 is "not known", an answer.
QUOTA_CODES = {
    430: 'the day\'s request quota is spent',
    431: 'the day\'s quota of roms it did not recognise is spent',
}
REFUSED_CODES = {
    401: 'the API is closed to non-members for now (server overloaded); try again later',
    403: 'the developer id or password was refused; check .env',
    423: 'the API is closed for now; try again later',
    426: 'this software name has been blocked or is out of date',
}
# Below the account's stated rate rather than at it, so clock drift on either side cannot tip a
# run over the line.
MARGIN = 1.2


class Pace:
    """Every request to ScreenScraper waits its turn here: API calls and image downloads alike,
    across every thread. Requests are spaced to the account's per-minute rate and counted against
    what is left of its day, so a run stops on its own before ScreenScraper has to stop it."""

    def __init__(self, per_min=None, day_left=None):
        # Until the account's limits are known, one request a second.
        self.gap = MARGIN * 60.0 / per_min if per_min else 1.0
        self.day_left = day_left
        self.used = 0
        self.next_at = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            if self.day_left is not None and self.used >= self.day_left:
                raise QuotaSpent('the day\'s request quota is spent')
            now = time.monotonic()
            at = max(now, self.next_at)
            self.next_at = at + self.gap
            self.used += 1
        if at > now:
            time.sleep(at - now)

    def hold(self, seconds):
        """Nothing goes out for `seconds`, on any thread: ScreenScraper asked for room."""
        with self.lock:
            self.next_at = max(self.next_at, time.monotonic() + seconds)


PACE = Pace()


def pace(q):
    """Pace every later request to the limits `quota` read, and say what they are."""
    global PACE
    left = None if q['per_day'] is None else max(0, q['per_day'] - q['today'])
    PACE = Pace(q['per_min'], left)
    print(f"quota: {q['today']} of {q['per_day'] or '?'} requests used today, "
          f"{q['per_min'] or '?'} a minute allowed, so one every {PACE.gap:.1f}s; "
          f"{q['ko_today']} of {q['ko_per_day'] or '?'} unrecognised roms today", flush=True)
    if left == 0:
        sys.exit('the day\'s quota is already spent; run again tomorrow and it will carry on')
    return left


def request(url, tries=4, timeout=60):
    """One paced GET to ScreenScraper. The body, or None for a 404.

    A 429 (too fast, or too many threads) backs off for as long as the reply's Retry-After says,
    or longer each time, and holds every other thread back with it. Quota codes raise QuotaSpent
    and refusals raise Refused; neither is retried. A dropped connection is retried a few times.
    """
    for attempt in range(tries):
        PACE.wait()
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in QUOTA_CODES:
                raise QuotaSpent(f'ScreenScraper says {QUOTA_CODES[e.code]} (HTTP {e.code})')
            if e.code in REFUSED_CODES:
                raise Refused(f'ScreenScraper says {REFUSED_CODES[e.code]} (HTTP {e.code})')
            if e.code == 429 and attempt < tries - 1:
                wait = retry_after(e) or 30 * (attempt + 1)
                print(f'    asked to slow down, waiting {wait}s', flush=True)
                PACE.hold(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
            PACE.hold(5 * (attempt + 1))
    return None


def retry_after(e):
    try:
        return max(0, int(e.headers.get('Retry-After', '')))
    except (TypeError, ValueError):
        return None


def call(endpoint, params, tries=4):
    """One API call's JSON, or None when ScreenScraper does not know the rom."""
    body = request(f'{API}/{endpoint}?' + urllib.parse.urlencode(params), tries)
    if body is None:
        return None
    try:
        return json.loads(body.decode('utf-8', 'replace'))
    except json.JSONDecodeError:
        # ScreenScraper answers some errors with a plain-text page and a 200.
        text = body.decode('utf-8', 'replace').strip()[:200]
        raise RuntimeError(f'ScreenScraper sent no JSON: {text}')


def quota(c):
    """The account's own limits. Their documentation makes honouring these the client's job."""
    data = call('ssuserInfos.php', c) or {}
    u = data.get('response', {}).get('ssuser', {}) or {}
    def num(*keys):
        for k in keys:
            v = u.get(k)
            if v not in (None, ''):
                try:
                    return int(str(v).strip())
                except ValueError:
                    pass
        return None
    return {
        'per_min': num('maxrequestspermin', 'maxrequestsparminute'),
        'per_day': num('maxrequestsperday', 'maxrequestsparjour'),
        'today': num('requeststoday', 'requestsdone') or 0,
        'threads': num('maxthreads') or 1,
        'ko_per_day': num('maxrequestskoperday'),
        'ko_today': num('requestskotoday') or 0,
    }


def dat_entries(platform):
    """CRC32 to No-Intro name: which dumps exist, and what to call them in this run's own output.

    The name never reaches a file on disk — those are named for the CRC — so this is a worklist
    and a log, not a source.
    """
    url = DAT + urllib.parse.quote(PLATFORMS[platform]) + '.dat'
    with urllib.request.urlopen(url, timeout=120) as r:
        text = r.read().decode('utf-8', 'replace')
    out = {}
    for block in re.finditer(r'game\s*\((.*?)\n\)', text, re.S):
        body = block.group(1)
        name = re.search(r'name\s+"([^"]+)"', body)
        crc = re.search(r'\bcrc\s+([0-9A-Fa-f]{8})', body)
        if name and crc:
            out[crc.group(1).upper()] = name.group(1)
    return out


def check_systems(c):
    """Hold ScreenScraper to the ids above, by the name it gives each one."""
    data = call('systemesListe.php', c)
    listed = (data or {}).get('response', {}).get('systemes', [])
    if not listed:
        sys.exit('ScreenScraper would not list its systems: check the credentials')
    names = {}
    for s in listed:
        try:
            names[int(s['id'])] = str((s.get('noms') or {}).get('nom_eu', '')).strip().lower()
        except (TypeError, ValueError):
            continue
    for platform, sid in SS_SYSTEM.items():
        got = names.get(sid)
        if got is None:
            sys.exit(f'ScreenScraper lists no system {sid}, which this expects to be {platform}')
        if got != SS_EXPECT[platform]:
            sys.exit(f'system {sid} is "{got}", not "{SS_EXPECT[platform]}": ids have moved')
    return SS_SYSTEM


def crc_skip(path):
    """No-Intro hashes a SNES dump without the 512-byte copier header some carry in front."""
    path = Path(path)
    if path.suffix.lower() in EXTENSIONS['SNES'] and path.stat().st_size % 1024 == 512:
        return 512
    return 0


def crc32(path):
    h = 0
    with open(path, 'rb') as f:
        f.seek(crc_skip(path))
        while chunk := f.read(1 << 20):
            h = zlib.crc32(chunk, h)
    return f'{h & 0xffffffff:08X}'


def pick(medias, want, regions=REGIONS):
    """The wanted media in the most useful region, or None."""
    same = [m for m in medias if m.get('type') == want]
    for region in regions:
        for m in same:
            if (m.get('region') or '').lower() == region:
                return m
    return same[0] if same else None


def fetch(url):
    """A media file. ScreenScraper serves these through its API, so they are paced and counted
    like any other request."""
    body = request(url, timeout=120)
    # A truncated or error body is not an image, and a broken file on the card is worse than none.
    return body if body and len(body) >= 256 else None


def as_png(body):
    if not body or body.startswith(b'\x89PNG\r\n\x1a\n'):
        return body
    try:
        import io
        from PIL import Image
        out = io.BytesIO()
        Image.open(io.BytesIO(body)).save(out, 'PNG')
        return out.getvalue()
    except Exception:
        return None


def save(body, dest):
    if not body:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return True


# `look` is not a ScreenScraper media: it is measured from the cart scan and kept in the index.
SOURCE = {'look': 'support-2D'}


def write_index(path, index):
    """Compact, since the page downloads it whole; sorted, so two runs diff cleanly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, separators=(',', ':'), sort_keys=True))


def todo_for(crc, wanted, index, root, relook, redo=False):
    """The media this cart still needs: files not on disk, and a look not yet recorded."""
    if redo:
        return list(wanted)
    def needed(w):
        if w == 'look':
            return relook or 'look' not in index.get(crc, {})
        return not (root / w / f'{crc}.png').exists()
    return [w for w in wanted if needed(w)]


def roms(card, platform):
    d = Path(card) / 'Games' / platform
    if not d.is_dir():
        return []
    return sorted(
        p for p in d.iterdir()
        if p.is_file() and not p.name.startswith('.') and p.suffix.lower() in EXTENSIONS[platform]
    )


def probe(path, c, ids):
    platform = Path(path).parent.name.upper()
    system = ids.get(platform)
    data = call('jeuInfos.php', dict(c, crc=crc32(path), systemeid=system or '',
                                     romnom=Path(path).name,
                                     romtaille=str(Path(path).stat().st_size)))
    jeu = (data or {}).get('response', {}).get('jeu')
    if not jeu:
        print(f'{Path(path).name}: no match')
        return
    names = jeu.get('noms') or [{}]
    print(f'{Path(path).name}: {names[0].get("text", "?")}  (system {system})')
    for m in jeu.get('medias', []):
        # The media urls carry devid and devpassword as query parameters, so only the path is
        # ever printed: a probe's output gets pasted into chats and issues.
        url = urllib.parse.urlsplit(str(m.get('url', '')))
        print(f'   {str(m.get("type")):<22} {str(m.get("region") or "-"):<5} '
              f'{str(m.get("format") or "-"):<5} {url.netloc}{url.path}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--card', help='a slot SD card, harvested for the roms actually on it')
    ap.add_argument('--dat', choices=sorted(PLATFORMS) + ['all'],
                    help='every dump a platform has, not just a card; "all" for every platform')
    ap.add_argument('--out', help='where the set is written')
    ap.add_argument('--media', default='wheel,look,support-texture',
                    help='comma separated ScreenScraper media types, or look for the label measured from the cart scan')
    ap.add_argument('--relook', action='store_true', help='measure every look again')
    ap.add_argument('--reregion', action='store_true', help='fetch every media again for dumps whose own region is not USA')
    ap.add_argument('--probe', help='print every media one rom has, and stop')
    ap.add_argument('--limit', type=int, help='stop after this many games, for a trial run')
    args = ap.parse_args()

    c = creds()
    ids = check_systems(c)

    if args.probe:
        probe(args.probe, c, ids)
        return
    if not args.out or not (args.card or args.dat):
        sys.exit('--out plus one of --card or --dat is needed (or --probe)')

    q = quota(c)
    pace(q)

    wanted = [m.strip() for m in args.media.split(',') if m.strip()]
    if 'look' in wanted:
        try:
            global look
            import look
        except ImportError:
            sys.exit('measuring looks needs Pillow and numpy: python3 -m pip install Pillow numpy, or pass --media wheel')
    index_path = Path(args.out) / 'index.json'
    index = json.loads(index_path.read_text()) if index_path.exists() else {}

    # The account's own thread allowance, which is what ScreenScraper polices. Every request
    # waits on the one shared pace, so the total stays inside the per-minute limit however many
    # threads are running.
    threads = max(1, min(q['threads'] or 1, 6))
    print(f'{threads} worker(s)')

    lock = threading.Lock()
    stop = threading.Event()
    n = {'asked': 0, 'saved': 0, 'missed': 0, 'skipped': 0, 'done': 0}

    def work(platform, root, system, entries, job):
        crc, romname, size = job
        if stop.is_set():
            return
        # The dat's name is only ever what this run calls a cart while it works; a rom it has
        # never heard of goes by its checksum, which is what the file is named anyway.
        name = entries.get(crc, crc)
        regions = regions_for(entries.get(crc) or romname)
        redo = args.reregion and regions[0] != 'us'
        todo = todo_for(crc, wanted, index, root, args.relook, redo)
        if not todo:
            with lock:
                n['skipped'] += 1
            return
        with lock:
            if args.limit and n['asked'] >= args.limit:
                stop.set()
                return
            n['asked'] += 1
        params = dict(c, crc=crc, systemeid=system, romnom=romname)
        if size:
            params['romtaille'] = str(size)
        try:
            data = call('jeuInfos.php', params)
        except (QuotaSpent, Refused) as e:
            if not stop.is_set():
                print(f'\nstopped: {e}', flush=True)
            stop.set()
            return
        except Exception as e:  # one bad game must not take the run down with it
            with lock:
                n['missed'] += 1
            print(f'  {name}: {type(e).__name__}')
            return
        medias = ((data or {}).get('response', {}).get('jeu') or {}).get('medias', [])
        got, measured = [], None
        for want in todo:
            m = pick(medias, SOURCE.get(want, want), regions)
            try:
                body = fetch(m['url']) if m else None
            except (QuotaSpent, Refused) as e:
                if not stop.is_set():
                    print(f'\nstopped: {e}', flush=True)
                stop.set()
                break
            except Exception:
                continue
            try:
                if want == 'look':
                    measured = look.measure_look(body) if body else None
                    if measured:
                        got.append(want)
                elif save(as_png(body), root / want / f'{crc}.png'):
                    got.append(want)
            except Exception:
                pass
        with lock:
            if got:
                n['saved'] += len(got)
                entry = index.setdefault(crc, {})
                for w in got:
                    entry[w] = measured if w == 'look' else str((root / w / f'{crc}.png').relative_to(args.out))
            else:
                n['missed'] += 1
            n['done'] += 1
            if n['done'] % 50 == 0:
                print(f"  ... {n['done']} done, {n['saved']} files, {n['missed']} without art", flush=True)

    try:
        chosen = list(PLATFORMS) if args.dat == 'all' else ([args.dat] if args.dat else list(PLATFORMS))
        for platform in chosen:
            if stop.is_set():
                break
            entries = dat_entries(platform)
            if args.card:
                # Every rom on the card, whether No-Intro knows it or not: a file is named for its
                # checksum, so a dump nobody has catalogued still has somewhere to go. Only a
                # sweep of a whole platform needs the dat, because only that needs a list.
                jobs = [(crc32(p), p.name, p.stat().st_size) for p in roms(args.card, platform)]
            else:
                jobs = [(crc, f'{name}.bin', 0) for crc, name in entries.items()]
            if not jobs:
                continue
            system = ids[platform]
            root = Path(args.out) / platform
            print(f'{platform}: {len(jobs)} to consider, system {system}', flush=True)
            with ThreadPoolExecutor(max_workers=threads) as pool:
                for job in jobs:
                    if stop.is_set():
                        break
                    pool.submit(work, platform, root, system, entries, job)
    except QuotaSpent as e:
        print(f'\nstopped: {e}')
    except KeyboardInterrupt:
        stop.set()
        print('\nstopped by hand')
    finally:
        asked, saved, missed, skipped = n['asked'], n['saved'], n['missed'], n['skipped']
        # Written whatever happened, so an interrupted run leaves a usable index behind.
        if args.out:
            write_index(index_path, index)
            print(f'\n{saved} files, {missed} games with none, {skipped} already there, '
                  f'{asked} api calls\nindex: {index_path} ({len(index)} crcs)')


if __name__ == '__main__':
    main()
