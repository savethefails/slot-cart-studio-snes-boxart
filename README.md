# slot cart studio (ezGBA)

Cart labels and box art for an [ezGBA](https://github.com/savethefails/ezGBA-640x480) SD card,
previewed on the same cart face the frontend draws. ezGBA is a fork of
[slot](https://slot-cfw.fyi); this studio is a fork of slot's own
[cart studio](https://github.com/BrandonKowalski/slot-cart-studio), built against ezGBA's source
instead so its carts, SNES included, are drawn exactly as the device draws them.

## What it writes

Open the root of the card in the studio. For each rom under `Games/GBA`, `Games/GB`, `Games/GBC`
and `Games/SNES` it writes:

- `Labels/<SYSTEM>/<rom name>.png`: the cart's label. When ScreenScraper has a scan of the real
  label it's used by default. Otherwise the label is made from the game's logo.
- `Images/<SYSTEM>/<rom name>.png`: box art shown above the shelf. This is libretro's 2D box front,
  and the studio only writes it for carts that don't have box art yet. Untick **Box art too** to
  skip it.

Roms are matched by checksum against No-Intro. SNES dumps with a 512-byte copier header match too.

## 3D box art

3D boxes are only on ScreenScraper, which a browser can't query, so a local script fetches them
instead. You'll need a [ScreenScraper](https://www.screenscraper.fr/) account (developer id and
password plus your user login), and the script respects the account's quota:

    SS_DEVID=... SS_DEVPASSWORD=... SS_SSID=... SS_SSPASSWORD=... \
        python3 tools/boxart.py --card /Volumes/SLOT --replace

`--replace` writes over the 2D boxes the studio wrote. Leave it off to fill only the carts that
have no box art yet. `--media box-2D` fetches ScreenScraper's flat fronts, and `--platform SNES`
limits the run to one system.

## Building

The WASM is built from this crate and four of the frontend's own source files, so ezGBA is checked
out beside it as `../slot` at the commit `slot.ref` names:

    git clone https://github.com/savethefails/ezGBA-640x480 ../slot
    git -C ../slot checkout "$(cat slot.ref)"
    task check && task serve

## License

GPL-3.0-or-later, same as slot. See [LICENSE](LICENSE).

Game names and CRCs come from
[libretro-database](https://github.com/libretro/libretro-database) (CC BY-SA 4.0). Logos come
from [ScreenScraper](https://www.screenscraper.fr/) (CC BY-NC-SA 4.0) and
[libretro-thumbnails](https://github.com/libretro-thumbnails/libretro-thumbnails), and box art comes
from libretro-thumbnails.

Game Boy and Super Nintendo are trademarks of Nintendo. Not affiliated with Nintendo.
