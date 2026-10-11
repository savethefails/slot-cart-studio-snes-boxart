#!/usr/bin/env python3
"""Box art and labels from ScreenScraper, for the roms in one folder, written where ezGBA reads them.

The studio in the browser can only reach libretro, which has 2D box fronts and no label scans.
ScreenScraper has all three, but wants credentials and sends no CORS headers, so this runs
locally instead, with the same credentials and quota handling as harvest.py: every request,
image downloads included, is spaced to the account's per-minute rate and counted against its day,
and ScreenScraper asking it to slow down or stop is obeyed rather than retried around.

    SS_DEVID=... SS_DEVPASSWORD=... SS_SSID=... SS_SSPASSWORD=... \\
        tools/scrape.py /Volumes/SLOT

One API call per rom brings back every media it has, and each lands in the card's own layout:

    Images/<SYSTEM>/<rom name>.png             the 3D box, which ezGBA shows above the shelf
    Images/<SYSTEM>/2dboxart/<rom name>.png    the flat 2D box front, kept beside it
    Labels/<SYSTEM>/<rom name>.png             the scan of the real cart label

A game with no 3D box gets its 2D box in Images/<SYSTEM>/ instead, so the shelf still shows one.

The folder can be a card's root (roms under Games/<SYSTEM>/), one system's folder such as
Games/SNES, or any folder of roms, where a rom's system is the folder it sits in when that is
named GBA, GB, GBC or SNES, and its extension otherwise. Only those roms are looked up; nothing
else is fetched. Files already there are kept unless --replace is given, and a rom whose files
are all there costs no API call.

The images are ScreenScraper's (CC BY-NC-SA 4.0) and stay on your machine.
"""

import argparse
import sys
from pathlib import Path

import harvest

# What each kind is called on ScreenScraper, and where it goes under the output folder.
KINDS = {
    'box-3D': ('box-3D', lambda p, stem: Path('Images') / p / f'{stem}.png'),
    'box-2D': ('box-2D', lambda p, stem: Path('Images') / p / '2dboxart' / f'{stem}.png'),
    'label': ('support-texture', lambda p, stem: Path('Labels') / p / f'{stem}.png'),
}
# A loose rom's system when its folder does not say: .gb and .gbc follow their extension here,
# since there is no card folder to decide it.
BY_EXTENSION = {'.gba': 'GBA', '.gb': 'GB', '.gbc': 'GBC', '.sfc': 'SNES', '.smc': 'SNES'}


def find_roms(folder):
    """Every rom under `folder` as (system, path), in a stable order.

    A card root is read the way slot reads it, Games/<SYSTEM>/ only. Anything else is walked
    whole, skipping dotfiles (macOS's ._ sidecars carry the rom's extension too).
    """
    folder = Path(folder)
    if (folder / 'Games').is_dir():
        return [(p, rom) for p in harvest.PLATFORMS for rom in harvest.roms(folder, p)]
    out = []
    for rom in sorted(folder.rglob('*')):
        if not rom.is_file() or any(part.startswith('.') for part in rom.relative_to(folder).parts):
            continue
        named = rom.parent.name.upper()
        if named in harvest.PLATFORMS:
            if rom.suffix.lower() in harvest.EXTENSIONS[named]:
                out.append((named, rom))
        elif rom.suffix.lower() in BY_EXTENSION:
            out.append((BY_EXTENSION[rom.suffix.lower()], rom))
    return out


def targets(out, platform, rom, kinds):
    """Where each wanted kind goes for one rom."""
    return {k: Path(out) / KINDS[k][1](platform, rom.stem) for k in kinds}


def missing(dests, replace):
    return {k: d for k, d in dests.items() if replace or not d.exists()}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('folder', help='a card root, one system\'s folder, or any folder of roms')
    ap.add_argument('--out', help='where Images/ and Labels/ go (default: the card root, or the folder itself)')
    ap.add_argument('--only', default=','.join(KINDS),
                    help=f'comma separated, any of {", ".join(KINDS)} (default: all)')
    ap.add_argument('--platform', choices=sorted(harvest.PLATFORMS), action='append',
                    help='only this system; repeat for several (default: all)')
    ap.add_argument('--replace', action='store_true', help='fetch again and write over files already there')
    ap.add_argument('--dry-run', action='store_true', help='list what would be fetched, and stop')
    args = ap.parse_args()

    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        sys.exit(f'{folder} is not a folder')
    kinds = [k.strip() for k in args.only.split(',') if k.strip()]
    unknown = [k for k in kinds if k not in KINDS]
    if unknown:
        sys.exit(f'--only takes {", ".join(KINDS)}, not {", ".join(unknown)}')
    out = Path(args.out).expanduser() if args.out else folder

    todo = []
    for platform, rom in find_roms(folder):
        if args.platform and platform not in args.platform:
            continue
        dests = missing(targets(out, platform, rom, kinds), args.replace)
        if dests:
            todo.append((platform, rom, dests))
    if not todo:
        print('every rom already has what was asked for (pass --replace to fetch it again)')
        return
    print(f'{len(todo)} roms to look up')
    if args.dry_run:
        for platform, rom, dests in todo:
            print(f'  {platform}/{rom.name}: {", ".join(dests)}')
        return

    c = harvest.creds()
    try:
        ids = harvest.check_systems(c)
        # From here on every request, image downloads included, goes through harvest's shared
        # pace: spaced to the account's per-minute rate and counted against what is left today.
        harvest.pace(harvest.quota(c))
    except (harvest.QuotaSpent, harvest.Refused) as e:
        sys.exit(f'stopped: {e}')

    def image(m):
        """One media file as PNG, or None. A quota or refusal stops the run; anything else only
        loses this one file."""
        if not m:
            return None
        try:
            return harvest.as_png(harvest.fetch(m['url']))
        except (harvest.QuotaSpent, harvest.Refused):
            raise
        except Exception:
            return None

    files = looked = unmatched = 0
    try:
        for platform, rom, dests in todo:
            params = dict(c, crc=harvest.crc32(rom), systemeid=ids[platform], romnom=rom.name,
                          romtaille=str(rom.stat().st_size - harvest.crc_skip(rom)))
            try:
                data = harvest.call('jeuInfos.php', params)
            except (harvest.QuotaSpent, harvest.Refused):
                raise
            except Exception as e:  # one bad rom must not take the run down with it
                print(f'  {platform}/{rom.stem}: {e}')
                continue
            looked += 1
            jeu = (data or {}).get('response', {}).get('jeu')
            if not jeu:
                unmatched += 1
                print(f'  {platform}/{rom.stem}: not known to ScreenScraper')
                continue
            medias = jeu.get('medias', [])
            regions = harvest.regions_for(rom.name)
            got = {}
            for kind in dests:
                body = image(harvest.pick(medias, KINDS[kind][0], regions))
                if harvest.save(body, dests[kind]):
                    got[kind] = body
                    files += 1
            # No 3D box: the 2D one stands in where the shelf looks, unless something is there.
            main_box = Path(out) / KINDS['box-3D'][1](platform, rom.stem)
            if 'box-3D' in kinds and 'box-3D' not in got and not main_box.exists():
                flat = got.get('box-2D')
                if flat is None and 'box-2D' not in kinds:
                    flat = image(harvest.pick(medias, 'box-2D', regions))
                if harvest.save(flat, main_box):
                    got['box-2D in place of box-3D'] = flat
                    files += 1
            wanted = ', '.join(dests)
            print(f'  {platform}/{rom.stem}: {", ".join(got) or "nothing"}'
                  + ('' if set(dests) <= set(got) else f' (wanted {wanted})'), flush=True)
    except (harvest.QuotaSpent, harvest.Refused) as e:
        print(f'\nstopped: {e}. Run again later and it carries on from here.')
    except KeyboardInterrupt:
        print('\nstopped by hand')
    print(f'\n{files} files written for {looked} roms looked up, {unmatched} of them unknown to '
          f'ScreenScraper; {harvest.PACE.used} requests this run')

if __name__ == '__main__':
    main()
