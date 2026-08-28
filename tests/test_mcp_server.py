import importlib.util
import os
import pathlib
import tempfile
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
        self.assertIn("search_knowledge_base", module.TOOL_REGISTRY)
        self.assertIn("save_body_measurements", module.TOOL_REGISTRY)
        self.assertIn("get_body_measurements", module.TOOL_REGISTRY)

        self.assertTrue(callable(module.TOOL_REGISTRY["calculate_bmi"]))
        self.assertTrue(callable(module.TOOL_REGISTRY["analyze_product"]))
        self.assertTrue(callable(module.TOOL_REGISTRY["search_knowledge_base"]))
        self.assertTrue(callable(module.TOOL_REGISTRY["save_body_measurements"]))
        self.assertTrue(callable(module.TOOL_REGISTRY["get_body_measurements"]))

        self.assertEqual(len(module.TOOLS), 5)
        self.assertEqual(module.TOOLS[0].name, "calculate_bmi")
        self.assertEqual(module.TOOLS[1].name, "analyze_product")
        self.assertEqual(module.TOOLS[2].name, "search_knowledge_base")
        self.assertEqual(module.TOOLS[3].name, "save_body_measurements")
        self.assertEqual(module.TOOLS[4].name, "get_body_measurements")

    def test_knowledge_base_returns_matching_example(self):
        spec = importlib.util.spec_from_file_location("mcp_server", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        result = module.TOOL_REGISTRY["search_knowledge_base"]("ile białka na masę")

        self.assertTrue(result["found"])
        self.assertEqual(result["results"][0]["source"], "odzywianie-na-mase.md")

    def test_knowledge_base_returns_eating_disorder_conversation_rules(self):
        spec = importlib.util.spec_from_file_location("mcp_server", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        result = module.TOOL_REGISTRY["search_knowledge_base"](
            "zasady rozmowy z osobą z zaburzeniami odżywiania"
        )

        self.assertTrue(result["found"])
        self.assertEqual(result["results"][0]["source"], "zaburzenia-odzywiania.md")
        self.assertIn("bez oceniania", result["results"][0]["content"])

    def test_body_measurements_are_saved_and_read_back(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            os.environ["FITMENTOR_DB_PATH"] = str(pathlib.Path(temporary_directory) / "measurements.db")
            try:
                spec = importlib.util.spec_from_file_location("mcp_server", MODULE_PATH)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.TOOL_REGISTRY["save_body_measurements"](
                    weight_kg=82.4,
                    circumferences_cm={"biceps": 35, "udo": 58.5},
                )
                result = module.TOOL_REGISTRY["get_body_measurements"]()
            finally:
                os.environ.pop("FITMENTOR_DB_PATH", None)

        self.assertTrue(result["found"])
        self.assertEqual(result["latest"]["weight_kg"], 82.4)
        self.assertEqual(result["latest"]["circumferences_cm"]["biceps"], 35.0)


if __name__ == "__main__":
    unittest.main()
