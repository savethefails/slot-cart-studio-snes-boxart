//! What the page needs from a ROM's bytes: its game code, for the shell colour, and its CRC32,
//! to find it in the No-Intro DAT.

/// The four character game code at 0xAC, read the way `slot_store::gba` reads it: up to the
/// first NUL, trimmed, and empty when there's nothing there. A cart then gets the same shell it
/// gets on the device.
pub fn header_code(head: &[u8]) -> String {
    let Some(field) = head.get(0xac..0xb0) else {
        return String::new();
    };
    let end = field.iter().position(|b| *b == 0).unwrap_or(field.len());
    std::str::from_utf8(&field[..end])
        .map(|s| s.trim().to_string())
        .unwrap_or_default()
}

/// How far into a SNES dump a page has to read to find its internal header: past the HiROM
/// header at 0xFFC0, behind a copier header if there is one.
pub const SNES_HEAD_READ: usize = 0x10200;

/// A SNES ROM's 32-byte internal header, found where slot's `snes::header` looks for it: LoROM
/// at 0x7FC0, then HiROM at 0xFFC0, both 512 bytes further in when `len` says the dump carries
/// a copier header. Empty when neither place holds one whose checksum and complement agree.
pub fn snes_head(head: &[u8], len: u64) -> Vec<u8> {
    let skip = if len % 1024 == 512 { 512 } else { 0 };
    [0x7fc0, 0xffc0]
        .iter()
        .find_map(|at| {
            let bytes = head.get(skip + at..skip + at + 0x20)?;
            slot_store::snes::parse(bytes).map(|_| bytes.to_vec())
        })
        .unwrap_or_default()
}

/// No-Intro hashes a SNES dump without its copier header, the 512 bytes some dumps carry in
/// front of the rom, so the page skips that many before hashing.
pub fn crc_skip(platform: &str, len: u64) -> u64 {
    if platform == "SNES" && len % 1024 == 512 {
        512
    } else {
        0
    }
}

/// A ROM is up to 32 MB and the page reads it as a stream, so the hash is fed in pieces.
#[derive(Default)]
pub struct Crc32(crc32fast::Hasher);

impl Crc32 {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn update(&mut self, chunk: &[u8]) {
        self.0.update(chunk);
    }

    pub fn finish(self) -> u32 {
        self.0.finalize()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A LoROM header at 0x7FC0: a title, then a checksum and its complement that agree.
    fn snes_rom(copier: bool, title: &str) -> Vec<u8> {
        let skip = if copier { 512 } else { 0 };
        let mut rom = vec![0u8; skip + 0x8000];
        let at = skip + 0x7fc0;
        let mut name = [b' '; 21];
        name[..title.len()].copy_from_slice(title.as_bytes());
        rom[at..at + 21].copy_from_slice(&name);
        rom[at + 0x1c..at + 0x1e].copy_from_slice(&0x1234u16.to_le_bytes());
        rom[at + 0x1e..at + 0x20].copy_from_slice(&(0x1234u16 ^ 0xffff).to_le_bytes());
        rom
    }

    #[test]
    fn a_snes_header_is_found_with_or_without_a_copier_header() {
        for copier in [false, true] {
            let rom = snes_rom(copier, "KILLER INSTINCT");
            let head = snes_head(&rom, rom.len() as u64);
            assert_eq!(head.len(), 0x20, "copier {copier}");
            assert_eq!(
                slot_store::snes::parse(&head).unwrap().title,
                "KILLER INSTINCT"
            );
        }
    }

    #[test]
    fn bytes_with_no_snes_header_give_none() {
        assert!(snes_head(&[0u8; 0x10000], 0x10000).is_empty());
        assert!(snes_head(&[], 0).is_empty());
    }

    #[test]
    fn only_a_snes_dump_with_a_copier_header_skips_it() {
        assert_eq!(crc_skip("SNES", 0x80200), 512);
        assert_eq!(crc_skip("SNES", 0x80000), 0);
        assert_eq!(crc_skip("GBA", 0x80200), 0);
    }

    #[test]
    fn the_check_value_is_the_standard_one() {
        let mut crc = Crc32::new();
        crc.update(b"123456789");
        assert_eq!(crc.finish(), 0xCBF4_3926);
    }

    #[test]
    fn chunks_hash_the_same_as_one_update() {
        let data: Vec<u8> = (0..100_000u32).map(|i| (i * 7 % 251) as u8).collect();
        let mut whole = Crc32::new();
        whole.update(&data);
        let mut parts = Crc32::new();
        for chunk in data.chunks(4113) {
            parts.update(chunk);
        }
        assert_eq!(whole.finish(), parts.finish());
    }

    #[test]
    fn the_code_stops_at_a_nul_and_is_empty_when_missing() {
        let mut head = vec![0u8; 0xb0];
        head[0xac..0xb0].copy_from_slice(b"AB\0\0");
        assert_eq!(header_code(&head), "AB");
        assert_eq!(header_code(&[0u8; 0xb0]), "");
        assert_eq!(header_code(&[0u8; 0x20]), "");
    }
}
