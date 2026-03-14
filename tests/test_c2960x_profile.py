from __future__ import annotations

import unittest

from ciscoautoflash.profiles import build_c2960x_profile


class Cisco2960XProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = build_c2960x_profile()

    def test_parse_version_extracts_key_fields(self) -> None:
        output = (
            "Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E13\n"
            'System image file is "flash:/c2960x-universalk9-mz.152-7.E13.bin"\n'
            "Model Number                    : WS-C2960X-48FPS-L\n"
            "switch uptime is 2 weeks, 5 days\n"
        )

        info = self.profile.parse_version(output)

        self.assertEqual(info.version, "15.2(7)E13")
        self.assertEqual(info.image, "flash:/c2960x-universalk9-mz.152-7.E13.bin")
        self.assertEqual(info.model, "WS-C2960X-48FPS-L")
        self.assertEqual(info.uptime, "2 weeks")

    def test_parse_storage_extracts_total_and_free_bytes(self) -> None:
        output = "123456789 bytes total (98765432 bytes free)"

        storage = self.profile.parse_storage(output)

        self.assertEqual(storage.total_bytes, 123456789)
        self.assertEqual(storage.free_bytes, 98765432)


if __name__ == "__main__":
    unittest.main()
