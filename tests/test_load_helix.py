import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "load_helix", ROOT / "scripts" / "load_helix.py"
)
load_helix = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(load_helix)


class CollapseTests(unittest.TestCase):
    def test_final_lifecycle_keeps_latest_judgment(self):
        judged = {
            "repository": "acme/app",
            "pull_request": 7,
            "event": "synchronize",
            "judged_at": "2026-11-01T10:00:00Z",
            "author_login": "dev",
            "ai_generated": True,
            "created_at": "2026-11-01T08:00:00Z",
            "pr_state": "open",
        }
        merged = {
            "repository": "acme/app",
            "pull_request": 7,
            "event": "merged",
            "judged_at": "2026-11-01T12:00:00Z",
            "merged": True,
            "merged_at": "2026-11-01T11:00:00Z",
            "pr_state": "merged",
            "ci_first_attempts": 2,
            "ci_first_passes": 1,
        }

        row = load_helix.collapse([judged, merged])[0]

        self.assertTrue(row["ai_generated"])
        self.assertEqual(row["pr_state"], "merged")
        self.assertEqual(row["lead_time_hours"], 3)
        self.assertEqual(row["ci_first_attempts"], 2)


class DeveloperMetricTests(unittest.TestCase):
    def test_strong_signals_require_three_completed_examples(self):
        rows = []
        for number, lead in enumerate((24, 36, 48), start=1):
            rows.append(
                {
                    "pull_request": number,
                    "author_login": "dev",
                    "pr_state": "merged",
                    "lead_time_hours": lead,
                    "ci_first_attempts": 1,
                    "ci_first_passes": 1,
                    "workflow_failures": 0,
                    "changes_requested": 0 if number < 3 else 1,
                    "review_iterations": 1 if number == 3 else 0,
                }
            )

        metric = load_helix.developer_metrics(rows)[0]

        self.assertEqual(metric["delivery_level"], "Strong")
        self.assertEqual(metric["quality_level"], "Strong")
        self.assertEqual(metric["closed_pr_completion_rate"], 100)
        self.assertEqual(metric["median_merge_lead_time_hours"], 36)
        self.assertEqual(metric["ci_first_pass_rate"], 100)
        self.assertEqual(metric["review_rework_prs"], 1)

    def test_small_sample_is_insufficient(self):
        metric = load_helix.developer_metrics(
            [
                {
                    "author_login": "dev",
                    "pr_state": "merged",
                    "lead_time_hours": 12,
                    "ci_first_attempts": 1,
                    "ci_first_passes": 1,
                }
            ]
        )[0]

        self.assertEqual(metric["delivery_level"], "Insufficient evidence")
        self.assertEqual(metric["quality_level"], "Insufficient evidence")


if __name__ == "__main__":
    unittest.main()
