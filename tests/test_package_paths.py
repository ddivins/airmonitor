from __future__ import annotations

import unittest


class PackagePathTests(unittest.TestCase):
    def test_new_sgx_import_path_matches_compatibility_wrapper(self):
        from airmonitor.sensors.sgx.ps1_voc import CURRENT_COMBINED_READ as new_path
        from airmonitor.sensors.sgx_ps1_voc_1000 import CURRENT_COMBINED_READ as old_path

        self.assertEqual(new_path, old_path)

    def test_filter_plugin_descriptors_import_without_device_credentials(self):
        from airmonitor.filters.bento import BentoFilter
        from airmonitor.filters.levoit import LevoitFilter

        self.assertEqual(BentoFilter().info.name, "bento")
        self.assertEqual(LevoitFilter().info.name, "levoit")


if __name__ == "__main__":
    unittest.main()
