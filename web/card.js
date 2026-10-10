// A card, however the browser opened it. Chrome and Edge hand over a directory handle that can
// be written to. Everything else hands over a flat list of files with their paths, which can only
// be read, so the labels leave as a zip instead.

// slot files a cart under the folder its platform names, in Games/, Labels/, Images/, Saves/ and
// States/ alike, and the folder is what decides the platform: the rom is never opened to ask.
// The studio's shelves and tabs run in this order.
export const PLATFORMS = ['GBA', 'GBC', 'GB', 'SNES'];

// slot's own rule, from slot-store's platform.rs. A .gba under GB/ is not a Game Boy cart and is
// passed over in silence, the way slot passes over it.
const EXTENSIONS = { GBA: ['gba'], GB: ['gb', 'gbc'], GBC: ['gb', 'gbc'], SNES: ['sfc', 'smc'] };
const ANY_ROM = ['gba', 'gb', 'gbc', 'sfc', 'smc'];

const named = (dir) => PLATFORMS.find((p) => p === dir.toUpperCase());
const ext = (name) => name.slice(name.lastIndexOf('.') + 1).toLowerCase();
// Never a dotfile: macOS leaves `._` sidecars beside what it copies onto a card, extension and
// all, so the extension alone cannot tell them from the file they shadow.
const visible = (name) => !name.startsWith('.');
const isCart = (platform, name) => visible(name) && EXTENSIONS[platform].includes(ext(name));
const isRom = (name) => visible(name) && ANY_ROM.includes(ext(name));
const isPng = (name) => visible(name) && ext(name) === 'png';
const stemOf = (name) => name.slice(0, name.lastIndexOf('.'));

// macOS lists exFAT names decomposed, whatever form was written, so names are compared composed.
// What gets written is still the listing's own spelling. The platform is part of the key because
// a .gb and a .gba can share a stem — two different games, two different carts.
const labelKey = (platform, stem) => `${platform}/${stem.normalize('NFC')}`;
const byCart = (a, b) =>
  a.platform !== b.platform
    ? PLATFORMS.indexOf(a.platform) - PLATFORMS.indexOf(b.platform)
    : a.stem < b.stem
      ? -1
      : a.stem > b.stem
        ? 1
        : 0;

const NO_GAMES = 'That doesn’t look like a slot SD card. Be sure to select the root of the card.';
const UNREADABLE =
  'Your browser couldn’t read that folder. In Firefox, the card’s hidden .Spotlight-V100 folder or a file with an accented name like é can cause this.';
const OLD_SHELL_FILE =
  'This browser can’t open cart_shell.ini. Start the latest slot once, then choose the card again.';
const OLD_LAYOUT =
  'This card still keeps its roms loose in Games. Start slot once on the device to sweep them into GBA, GB, GBC and SNES folders, then choose the card again.';

export async function fromDirectory(root) {
  let games;
  try {
    games = await root.getDirectoryHandle('Games');
  } catch {
    throw new Error(NO_GAMES);
  }
  const carts = [];
  let sawPlatform = false;
  let loose = false;
  for await (const [name, handle] of games.entries()) {
    const platform = handle.kind === 'directory' ? named(name) : null;
    if (!platform) {
      if (handle.kind === 'file' && isRom(name)) loose = true;
      continue;
    }
    sawPlatform = true;
    for await (const [file, fh] of handle.entries()) {
      if (fh.kind === 'file' && isCart(platform, file)) {
        carts.push({ platform, stem: stemOf(file), file: () => fh.getFile() });
      }
    }
  }
  // A card swept by slot has the folders. One that has roms but no folders predates the sweep,
  // and slot does that sweep itself on the device rather than the studio doing it over the wire.
  if (!sawPlatform && loose) throw new Error(OLD_LAYOUT);

  // The PNGs a top folder holds per platform: labels in Labels/, box art in Images/.
  const pngs = async (top) => {
    const found = new Map();
    try {
      const dir = await root.getDirectoryHandle(top);
      for await (const [name, handle] of dir.entries()) {
        const platform = handle.kind === 'directory' ? named(name) : null;
        if (!platform) continue;
        for await (const [file, fh] of handle.entries()) {
          if (fh.kind === 'file' && isPng(file)) {
            found.set(labelKey(platform, stemOf(file)), () => fh.getFile());
          }
        }
      }
    } catch {
      // No such folder yet: every cart needs one.
    }
    return found;
  };
  const labels = await pngs('Labels');
  const images = await pngs('Images');

  // One PNG into <top>/<platform>/<stem>.png. One already on the card is skipped unless `replace`
  // says to write over it.
  const writeFile = async (top, platform, stem, bytes, replace) => {
    const root_dir = await root.getDirectoryHandle(top, { create: true });
    const dir = await root_dir.getDirectoryHandle(platform, { create: true });
    const name = `${stem}.png`;
    let existed = false;
    try {
      await dir.getFileHandle(name);
      existed = true;
      if (!replace) return 'skipped';
    } catch (e) {
      if (e.name !== 'NotFoundError') throw e;
    }
    // The file exists from here on, empty until the write closes. A write that fails (a full
    // card, permission withdrawn, the card pulled) must take it away again: an empty file left
    // behind reads as one the card already has, so the studio would never make this one.
    const file = await dir.getFileHandle(name, { create: true });
    let out = null;
    try {
      out = await file.createWritable();
      await out.write(bytes);
      await out.close();
    } catch (e) {
      await out?.abort().catch(() => {});
      // A file being replaced is left as it was: the write only lands when it closes.
      if (!existed) await dir.removeEntry(name).catch(() => {});
      throw e;
    }
    return 'written';
  };

  const shellFile = async (folder) => {
    let dir;
    try {
      dir = await root.getDirectoryHandle(folder);
    } catch (e) {
      if (e.name === 'NotFoundError') return null;
      throw e;
    }
    const read = async (name) => {
      try {
        return await (await (await dir.getFileHandle(name)).getFile()).text();
      } catch (e) {
        if (e.name === 'NotFoundError') return null;
        throw e;
      }
    };
    const txt = await read('cart_shell.txt');
    if (txt !== null) return txt;
    try {
      return await read('cart_shell.ini');
    } catch (e) {
      if (e.name !== 'TypeError') throw e;
      throw Object.assign(new Error(OLD_SHELL_FILE, { cause: e }), { name: 'OldShellFile' });
    }
  };
  const systemShells = async () => (await shellFile('Config')) ?? (await shellFile('System')) ?? '';
  const labelShells = async () => (await shellFile('Labels')) ?? '';

  return {
    carts: carts.sort(byCart),
    labels,
    images,
    direct: true,
    systemShells,
    labelShells,
    async writeShells(text) {
      const dir = await root.getDirectoryHandle('Labels', { create: true });
      const file = await dir.getFileHandle('cart_shell.txt', { create: true });
      const out = await file.createWritable();
      try {
        await out.write(text);
        await out.close();
      } catch (e) {
        await out.abort().catch(() => {});
        throw e;
      }
    },
    // A label already on the card is skipped unless `replace` says to write over it.
    write: (platform, stem, bytes, replace = false) => writeFile('Labels', platform, stem, bytes, replace),
    // Box art, where slot looks for it above the shelf. Never written over: art already on the
    // card is the owner's choice.
    writeImage: (platform, stem, bytes) => writeFile('Images', platform, stem, bytes, false),
  };
}

export function fromFiles(files) {
  if (files.length === 0) throw new Error(UNREADABLE);
  const carts = [];
  const labels = new Map();
  const images = new Map();
  const labelFiles = [];
  let sawPlatform = false;
  let loose = false;
  const shellFiles = {};
  for (const file of files) {
    const parts = file.webkitRelativePath.split('/');
    // Labels and Images both leave in the zip whole, so unzipping it over the card's own
    // folders loses nothing that was there.
    const top = { labels: 'Labels', images: 'Images' }[parts[1]?.toLowerCase()];
    if (parts.length >= 3 && top && parts.slice(2).every(visible)) {
      labelFiles.push({ path: [top, ...parts.slice(2)].join('/'), file: async () => file });
    }
    // The picked folder, then Games or Labels, then the platform, then the file. Anything
    // shallower is the layout slot swept away; anything deeper is not slot's.
    if (parts.length === 3) {
      const [, dir, name] = parts;
      if (dir.toLowerCase() === 'games' && isRom(name)) loose = true;
      const ext = ['cart_shell.txt', 'cart_shell.ini'].indexOf(name.toLowerCase());
      if (['config', 'system', 'labels'].includes(dir.toLowerCase()) && ext !== -1) {
        (shellFiles[dir.toLowerCase()] ??= [])[ext] = file;
      }
      continue;
    }
    if (parts.length !== 4) continue;
    const [, dir, folder, name] = parts;
    const platform = named(folder);
    if (!platform) continue;
    if (dir.toLowerCase() === 'games') {
      sawPlatform = true;
      if (isCart(platform, name)) carts.push({ platform, stem: stemOf(name), file: async () => file });
    } else if (dir.toLowerCase() === 'labels' && isPng(name)) {
      labels.set(labelKey(platform, stemOf(name)), async () => file);
    } else if (dir.toLowerCase() === 'images' && isPng(name)) {
      images.set(labelKey(platform, stemOf(name)), async () => file);
    }
  }
  if (!sawPlatform) throw new Error(loose ? OLD_LAYOUT : NO_GAMES);
  const text = async (files) => {
    const file = files?.[0] ?? files?.[1];
    return file ? file.text() : '';
  };
  return {
    carts: carts.sort(byCart),
    labels,
    images,
    labelFiles,
    direct: false,
    write: null,
    writeImage: null,
    systemShells: () => text(shellFiles.config ?? shellFiles.system),
    labelShells: () => text(shellFiles.labels),
  };
}

export { labelKey };
