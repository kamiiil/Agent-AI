import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "mcp_server.py"


class TestMcpServer(unittest.TestCase):
    def test_server_module_exports_tools(self):
        spec = importlib.util.spec_from_file_location("mcp_server", MODULE_PATH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertTrue(hasattr(module, "TOOL_REGISTRY"))
        self.assertIn("calculate_bmi", module.TOOL_REGISTRY)
        self.assertIn("analyze_product", module.TOOL_REGISTRY)

        self.assertTrue(callable(module.TOOL_REGISTRY["calculate_bmi"]))
        self.assertTrue(callable(module.TOOL_REGISTRY["analyze_product"]))

        self.assertEqual(len(module.TOOLS), 2)
        self.assertEqual(module.TOOLS[0].name, "calculate_bmi")
        self.assertEqual(module.TOOLS[1].name, "analyze_product")


if __name__ == "__main__":
    unittest.main()
