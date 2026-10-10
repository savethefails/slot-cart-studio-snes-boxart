//! A cart's shell choice as the page holds it: empty for Automatic.

use slot_store::{Cart, Outline, Platform, ShellChoice, ShellFinish};
use unicode_normalization::UnicodeNormalization;

use crate::shell::{self, Finish, Shell};

fn value_of(s: Shell) -> String {
    let finish = match s.finish {
        Finish::Solid => ShellFinish::Solid,
        Finish::Translucent => ShellFinish::Clear,
        Finish::Glitter => ShellFinish::Glitter,
    };
    ShellChoice {
        outline: Outline::Auto,
        colour: s.colour,
        finish,
    }
    .to_value()
}

/// The shell slot picks for this cart with no choice made, as a value.
pub fn auto_shell(platform: Platform, code: &str, head: &[u8]) -> String {
    slot_store::gb::with_header(head, |rom| {
        value_of(shell::shell_for(&Cart {
            platform,
            stem: String::new(),
            rom: rom.to_path_buf(),
            label: None,
            box_art: None,
            title: String::new(),
            code: code.to_string(),
            shell: None,
        }))
    })
}

/// The plastics the picker offers, named. Upstream slot keeps this list in `shell.rs`; ezGBA's
/// `shell.rs` has none, so it lives here. The GBA rows are read from slot's table by game code so
/// they cannot drift; the Game Boy rows are keyed on header fields slot keeps private, so their
/// colours are restated from ezGBA's `GB_CODES` and `GB_OVERSEAS_TITLES`.
fn shell_presets() -> Vec<(&'static str, Shell)> {
    const GBA: &[(&str, &str)] = &[
        ("Advance Video grey", "M"),
        ("Pokémon Ruby", "AXV"),
        ("Pokémon Sapphire", "AXP"),
        ("Pokémon Emerald", "BPE"),
        ("Pokémon FireRed", "BPR"),
        ("Pokémon LeafGreen", "BPG"),
        ("Boktai clear", "U3I"),
        ("Drill Dozer red", "V49"),
        ("Yoshi green", "KYGE"),
        ("WarioWare smoke", "RZW"),
        ("Made in Wario white", "RZWJ"),
    ];
    let solid = |colour| Shell {
        colour,
        finish: Finish::Solid,
    };
    let clear = |colour| Shell {
        colour,
        finish: Finish::Translucent,
    };
    let mut out = vec![
        ("Game Boy grey", shell::DMG_SHELL),
        ("Game Boy black", shell::DUAL_MODE_SHELL),
        ("Game Boy Color clear", shell::GB_CLEAR_SHELL),
        ("Advance charcoal", shell::DEFAULT_SHELL),
        ("Super Nintendo grey", shell::SNES_SHELL),
        ("Killer Instinct black", solid([0x2c, 0x2b, 0x2e])),
    ];
    out.extend(GBA.iter().map(|(n, k)| (*n, shell::gba_shell_for(k))));
    out.extend([
        ("Pokémon Gold", solid([0xb3, 0x8b, 0x3a])),
        ("Pokémon Silver", solid([0xa9, 0xaa, 0xa7])),
        (
            "Pokémon Crystal",
            Shell {
                colour: [0x86, 0xb9, 0xbf],
                finish: Finish::Glitter,
            },
        ),
        ("Kirby pink", clear([0xec, 0x94, 0xb4])),
        ("Command Master turquoise", clear([0x1f, 0x9f, 0xb6])),
        ("Chee-Chai Alien orange", clear([0xf0, 0xa9, 0x5e])),
        ("Pinball yellow", solid([0xe2, 0xb4, 0x13])),
        ("Pokémon Red", solid([0xc0, 0x28, 0x2c])),
        ("Pokémon Blue", solid([0x2b, 0x3a, 0x88])),
        ("Pokémon Yellow", solid([0xe9, 0xa8, 0x26])),
    ]);
    out
}

/// `name\tvalue` per preset.
pub fn presets() -> Vec<String> {
    shell_presets()
        .into_iter()
        .map(|(name, s)| format!("{name}\t{}", value_of(s)))
        .collect()
}

/// Set one key in ini text, leaving every other line as it was; `None` removes it. A key the
/// format cannot hold (one `parse` would read back differently) is refused. Upstream slot's
/// `ini::set`, which ezGBA's `ini.rs` does not have yet.
fn ini_set(text: &str, key: &str, value: Option<&str>) -> std::io::Result<String> {
    let probe = format!("{key} = {}", value.unwrap_or("x"));
    let back = slot_store::ini::parse(&probe);
    if probe.lines().count() != 1
        || back.len() != 1
        || back.get(key).map(String::as_str) != Some(value.unwrap_or("x"))
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            format!("cannot hold the entry {probe:?}"),
        ));
    }
    let is_key = |line: &str| {
        let parsed = slot_store::ini::parse(line);
        parsed.len() == 1 && parsed.contains_key(key)
    };
    let entry_line = value.map(|v| format!("{key} = {v}"));
    let mut out = String::with_capacity(text.len() + probe.len() + 1);
    let mut replaced = false;
    for line in text.lines() {
        if !is_key(line) {
            out.push_str(line);
            out.push('\n');
        } else if let (false, Some(new)) = (replaced, &entry_line) {
            out.push_str(new);
            out.push('\n');
            replaced = true;
        }
    }
    if let (false, Some(new)) = (replaced, &entry_line) {
        out.push_str(new);
        out.push('\n');
    }
    Ok(out)
}

/// Stem, value, stem, value: each cart's choice once `labels` is laid over `system`, as slot reads
/// the card's two files.
pub fn layered_cart_shells(system: &str, labels: &str) -> Vec<String> {
    slot_store::cart_shell::layered(system, labels)
        .into_iter()
        .flat_map(|(stem, c)| [stem, c.to_value()])
        .collect()
}

/// Stem, value, stem, value, for every line of `text` that parses; values normalised.
pub fn cart_shells(text: &str) -> Vec<String> {
    slot_store::cart_shell::choices(text)
        .into_iter()
        .flat_map(|(stem, c)| [stem, c.to_value()])
        .collect()
}

/// `text` with each stem set to its value, or removed where the value is empty. A key that is the
/// stem under a different Unicode normalisation (macOS lists exFAT names decomposed) is treated as
/// the same cart: it is dropped first, so the stem never ends up on two lines.
pub fn merge_cart_shells(
    text: &str,
    stems: &[String],
    values: &[String],
) -> std::io::Result<String> {
    let mut out = text.to_string();
    for (stem, value) in stems.iter().zip(values) {
        let nfc_stem: String = stem.nfc().collect();
        for key in slot_store::ini::parse(&out).into_keys() {
            if key != *stem && key.nfc().collect::<String>() == nfc_stem {
                out = ini_set(&out, &key, None)?;
            }
        }
        out = ini_set(&out, stem, (!value.is_empty()).then_some(value.as_str()))?;
    }
    Ok(out)
}

pub fn shell_key_ok(stem: &str) -> bool {
    ini_set("", stem, None).is_ok()
}
