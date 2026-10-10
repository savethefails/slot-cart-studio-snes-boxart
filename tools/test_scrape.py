"""Which roms scrape.py finds, and where their art goes. Run from tools/: python3 -m unittest test_scrape"""

import tempfile
import unittest
from pathlib import Path

import harvest
import scrape


def tree(files):
    root = Path(tempfile.mkdtemp())
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b'x')
    return root


class FindRoms(unittest.TestCase):
    def test_a_card_is_read_by_its_games_folders_only(self):
        root = tree(['Games/SNES/Zelda.sfc', 'Games/SNES/._Zelda.sfc', 'Games/GBA/Fusion.gba',
                     'Games/GB/Wrong.gba', 'Saves/GBA/Fusion.gba'])
        got = [(p, r.name) for p, r in scrape.find_roms(root)]
        self.assertEqual(got, [('GBA', 'Fusion.gba'), ('SNES', 'Zelda.sfc')])

    def test_a_loose_folder_goes_by_folder_name_then_extension(self):
        root = tree(['SNES/Mario.smc', 'GBC/Tetris.gb', 'mixed/Zelda.sfc', 'mixed/Kirby.gbc',
                     'mixed/notes.txt', '.Trash/Old.gba'])
        got = sorted((p, r.name) for p, r in scrape.find_roms(root))
        self.assertEqual(got, [('GBC', 'Kirby.gbc'), ('GBC', 'Tetris.gb'),
                               ('SNES', 'Mario.smc'), ('SNES', 'Zelda.sfc')])


class Targets(unittest.TestCase):
    def test_each_kind_lands_where_ezgba_reads_it(self):
        out = Path('/card')
        got = scrape.targets(out, 'SNES', Path('x/Zelda (USA).sfc'), list(scrape.KINDS))
        self.assertEqual(got, {
            'box-3D': out / 'Images/SNES/Zelda (USA).png',
            'box-2D': out / 'Images/SNES/2dboxart/Zelda (USA).png',
            'label': out / 'Labels/SNES/Zelda (USA).png',
        })

    def test_files_already_there_are_kept_unless_replaced(self):
        root = tree(['Labels/GBA/Fusion.png'])
        dests = scrape.targets(root, 'GBA', Path('Fusion.gba'), ['box-3D', 'label'])
        self.assertEqual(list(scrape.missing(dests, replace=False)), ['box-3D'])
        self.assertEqual(list(scrape.missing(dests, replace=True)), ['box-3D', 'label'])


class CopierHeader(unittest.TestCase):
    def test_a_snes_copier_header_is_left_out_of_the_checksum(self):
        root = Path(tempfile.mkdtemp())
        body = bytes(range(256)) * 8
        (root / 'plain.sfc').write_bytes(body)
        (root / 'copier.smc').write_bytes(b'\xff' * 512 + body)
        (root / 'odd.gba').write_bytes(b'\xff' * 512 + body)
        self.assertEqual(harvest.crc32(root / 'copier.smc'), harvest.crc32(root / 'plain.sfc'))
        self.assertNotEqual(harvest.crc32(root / 'odd.gba'), harvest.crc32(root / 'plain.sfc'))


if __name__ == '__main__':
    unittest.main()
