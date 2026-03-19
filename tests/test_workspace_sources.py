from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deep_researcher.workspace_sources import discover_workspace_documents, select_workspace_evidence


class WorkspaceSourcesTest(unittest.TestCase):
    def test_discover_workspace_documents_reads_text_csv_and_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "workspace_sources"
            source_dir.mkdir()
            (source_dir / "阳光电源2024年报.txt").write_text(
                "营业收入 722亿元\n净利润 94.4亿元\n海外收入占比提升\n",
                encoding="utf-8",
            )
            (source_dir / "阳光电源分业务.csv").write_text(
                "业务,收入占比,毛利率\n逆变器,61.53%,31.2%\n储能,32.06%,38.4%\n",
                encoding="utf-8",
            )
            (source_dir / "阳光电源估值.json").write_text(
                '{"pe_ttm": 18.6, "bps": 23.4, "eps_cagr": "31%"}',
                encoding="utf-8",
            )

            documents = discover_workspace_documents(
                project_root=root,
                configured_paths=[source_dir],
                question="研究阳光电源",
                max_documents=10,
                max_chars_per_document=10000,
            )

            self.assertEqual(len(documents), 3)
            joined = "\n".join(item.text for item in documents)
            self.assertIn("营业收入 722亿元", joined)
            self.assertIn("业务: 逆变器", joined)
            self.assertIn("pe_ttm: 18.6", joined)

    def test_select_workspace_evidence_prioritizes_matching_docs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "workspace_sources"
            source_dir.mkdir()
            (source_dir / "阳光电源2024年报.txt").write_text(
                "营业收入 722亿元\n净利润 94.4亿元\n储能业务收入占比 41%\n",
                encoding="utf-8",
            )
            (source_dir / "无关文档.txt").write_text(
                "这是一个无关的项目说明。",
                encoding="utf-8",
            )

            documents = discover_workspace_documents(
                project_root=root,
                configured_paths=[source_dir],
                question="研究阳光电源",
                max_documents=10,
                max_chars_per_document=10000,
            )
            evidence = select_workspace_evidence(
                documents=documents,
                question="研究阳光电源的收入结构和储能业务",
                section_title="产品线深度分析",
                section_queries=["阳光电源 储能 收入占比 毛利率"],
                must_cover=["储能收入占比", "产品线"],
                max_documents=2,
                max_chars_per_excerpt=1200,
            )

            self.assertEqual(len(evidence), 1)
            self.assertTrue(evidence[0].path.name.startswith("阳光电源"))
            self.assertIn("储能业务收入占比", evidence[0].excerpt)


if __name__ == "__main__":
    unittest.main()
