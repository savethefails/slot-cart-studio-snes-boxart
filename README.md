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

## Box art and labels from ScreenScraper, locally

ScreenScraper has 3D boxes, 2D boxes and scans of real cart labels, but a browser can't query
it, so `tools/scrape.py` does it on your machine instead. Point it at a folder: a card's root,
one system's folder like `Games/SNES`, or any folder of roms. Only the roms in that folder are
looked up, at one API call each:

    SS_DEVID=... SS_DEVPASSWORD=... SS_SSID=... SS_SSPASSWORD=... \
        python3 tools/scrape.py /Volumes/SLOT

| Kind | Written to |
| --- | --- |
| 3D box | `Images/<SYSTEM>/<rom name>.png`, which ezGBA shows above the shelf |
| 2D box | `Images/<SYSTEM>/2dboxart/<rom name>.png` |
| Label scan | `Labels/<SYSTEM>/<rom name>.png` |

- **No 3D box:** the 2D box goes in `Images/<SYSTEM>/` instead.
- **Files already there** are kept. Pass `--replace` to fetch again and write over them.
- **Other options:**
  - `--only box-3D,label` limits the kinds.
  - `--platform SNES` limits the systems.
  - `--out DIR` writes somewhere other than the folder itself.
  - `--dry-run` lists what would be fetched without spending quota.
- **Account:** you need a [ScreenScraper](https://www.screenscraper.fr/) developer id and
  password, plus your own user login. The script stays inside that account's daily quota, and
  a later run carries on from where it stopped.

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
