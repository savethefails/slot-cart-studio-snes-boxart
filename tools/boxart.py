#!/usr/bin/env python3
"""Put box art from ScreenScraper straight onto a card, where slot shows it above the shelf.

The studio writes libretro's 2D box fronts, which a browser can fetch. 3D boxes are only on
ScreenScraper, whose API wants credentials and sends no CORS headers, so the page cannot ask it.
This runs locally instead, with the same credentials and quota handling as harvest.py:

    SS_DEVID=... SS_DEVPASSWORD=... SS_SSID=... SS_SSPASSWORD=... \\
        tools/boxart.py --card /Volumes/SLOT --replace

Each rom under Games/<SYSTEM>/ is looked up by checksum and its box lands at
Images/<SYSTEM>/<rom name>.png. Art already there is left alone unless --replace is given, so a
run over a card the studio has already written to swaps the 2D boxes for 3D ones. --media box-2D
fetches ScreenScraper's flat fronts instead.

The images are ScreenScraper's (CC BY-NC-SA 4.0) and stay on your card; nothing is published.
"""

import argparse
import sys
import time
from pathlib import Path

import harvest


def target(card, platform, rom):
    """Where slot looks for a rom's box art: Images/<platform>/<rom stem>.png."""
    return Path(card) / 'Images' / platform / f'{Path(rom).stem}.png'


def jobs(card, platforms, replace):
    """Every rom on the card that still wants box art, as (platform, rom, destination)."""
    out = []
    for platform in platforms:
        for rom in harvest.roms(card, platform):
            dest = target(card, platform, rom)
            if replace or not dest.exists():
                out.append((platform, rom, dest))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--card', required=True, help='the root of a slot SD card')
    ap.add_argument('--media', default='box-3D', help='ScreenScraper media type: box-3D (default) or box-2D')
    ap.add_argument('--platform', choices=sorted(harvest.PLATFORMS), action='append',
                    help='only this system; repeat for several (default: all)')
    ap.add_argument('--replace', action='store_true', help='write over box art already on the card')
    args = ap.parse_args()

    if not (Path(args.card) / 'Games').is_dir():
        sys.exit(f'{args.card} has no Games folder: point --card at the root of a slot SD card')
    todo = jobs(args.card, args.platform or list(harvest.PLATFORMS), args.replace)
    if not todo:
        print('every rom already has box art (pass --replace to fetch it again)')
        return

    c = harvest.creds()
    ids = harvest.check_systems(c)
    q = harvest.quota(c)
    left = None if q['per_day'] is None else max(0, q['per_day'] - q['today'])
    if left == 0:
        sys.exit('the day\'s quota is already spent; run again tomorrow and it will resume')
    pause = 60.0 / q['per_min'] if q['per_min'] else 1.0
    print(f'{len(todo)} roms to look up, {left if left is not None else "unknown"} calls left today')

    saved = missed = asked = 0
    try:
        for platform, rom, dest in todo:
            if left is not None and asked >= left:
                print('the day\'s quota is spent; run again tomorrow to carry on')
                break
            asked += 1
            params = dict(c, crc=harvest.crc32(rom), systemeid=ids[platform], romnom=rom.name,
                          romtaille=str(rom.stat().st_size - harvest.crc_skip(rom)))
            try:
                data = harvest.call('jeuInfos.php', params)
                medias = ((data or {}).get('response', {}).get('jeu') or {}).get('medias', [])
                m = harvest.pick(medias, args.media, harvest.regions_for(rom.name))
                body = harvest.as_png(harvest.fetch(m['url'])) if m else None
            except harvest.QuotaSpent:
                raise
            except Exception as e:  # one bad rom must not take the run down with it
                print(f'  {platform}/{rom.stem}: {type(e).__name__}')
                body = None
            if harvest.save(body, dest):
                saved += 1
                print(f'  {platform}/{rom.stem}')
            else:
                missed += 1
                print(f'  {platform}/{rom.stem}: no {args.media}')
            time.sleep(pause)
    except harvest.QuotaSpent as e:
        print(f'\nstopped: {e}')
    except KeyboardInterrupt:
        print('\nstopped by hand')
    print(f'\n{saved} written, {missed} without {args.media}, {asked} api calls')


if __name__ == '__main__':
    main()
