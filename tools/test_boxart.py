"""Where box art goes on a card. Run from tools/: python3 -m unittest test_boxart"""

import tempfile
import unittest
from pathlib import Path

import boxart
import harvest


class Jobs(unittest.TestCase):
    def card(self):
        root = Path(tempfile.mkdtemp())
        for rel in ['Games/SNES/Zelda (USA).sfc', 'Games/SNES/Mario (USA).smc', 'Games/SNES/.hidden.sfc',
                    'Games/GBA/Fusion (USA).gba', 'Images/GBA/Fusion (USA).png']:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(b'x')
        return root

    def test_box_art_goes_where_slot_reads_it(self):
        root = self.card()
        self.assertEqual(boxart.target(root, 'SNES', root / 'Games/SNES/Zelda (USA).sfc'),
                         root / 'Images/SNES/Zelda (USA).png')

    def test_art_on_the_card_is_kept_unless_replaced(self):
        root = self.card()
        got = [(p, r.name) for p, r, _ in boxart.jobs(root, ['GBA', 'SNES'], replace=False)]
        self.assertEqual(got, [('SNES', 'Mario (USA).smc'), ('SNES', 'Zelda (USA).sfc')])
        got = [(p, r.name) for p, r, _ in boxart.jobs(root, ['GBA', 'SNES'], replace=True)]
        self.assertEqual(got, [('GBA', 'Fusion (USA).gba'), ('SNES', 'Mario (USA).smc'), ('SNES', 'Zelda (USA).sfc')])


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
