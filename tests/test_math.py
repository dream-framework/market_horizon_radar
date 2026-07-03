import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("update_live", ROOT / "scripts" / "update_live.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class MathTests(unittest.TestCase):
    def test_sigmoid_bounds(self):
        self.assertGreater(mod.sigmoid(-100), 0)
        self.assertLess(mod.sigmoid(-100), 0.01)
        self.assertGreater(mod.sigmoid(100), 0.99)
        self.assertLessEqual(mod.sigmoid(100), 1)

    def test_classify_text_detects_dust(self):
        signals = {
            "keywords": {
                "dust_cloud": ["bankruptcy"],
                "defensive_decay": ["weak demand"],
                "ridge_reach": ["expansion"],
                "geo_vector": ["war"],
                "macro_vector": ["recession"],
            }
        }
        scores = mod.classify_text("Company cites weak demand and bankruptcy risk", signals)
        self.assertGreater(scores["dust_cloud"], 0)
        self.assertGreater(scores["defensive_decay"], 0)

    def test_phase_for_probability(self):
        signals = {"phase_thresholds": [
            {"phase": "S0", "label": "normal", "max_probability": 0.3},
            {"phase": "S4", "label": "risk", "max_probability": 1.0},
        ]}
        self.assertEqual(mod.phase_for_probability(0.2, signals)["phase"], "S0")
        self.assertEqual(mod.phase_for_probability(0.8, signals)["phase"], "S4")

    def test_macro_only_cannot_create_phase(self):
        evidence = [
            {
                "source_type": "macro_series",
                "entity": "DGS10",
                "sector": "macro",
                "classification": {
                    "dust_cloud": 0,
                    "defensive_decay": 0,
                    "ridge_reach": 0,
                    "geo_vector": 0,
                    "macro_vector": 1.5,
                },
                "classes": ["macro_vector"],
            }
        ]
        current = mod.aggregate_current(evidence)
        self.assertEqual(current["sync"], 0)
        self.assertEqual(current["corporate_deformation_count"], 0)
        signals = {
            "min_history_points_for_baseline": 24,
            "min_sync_evidence_for_phase": 3,
            "min_corporate_deformation_evidence_for_phase": 2,
            "require_nonzero_dust_or_decay_for_phase": True,
            "probability": {
                "intercept": -0.35,
                "dust_cloud_z": 0.9,
                "defensive_decay_z": 0.7,
                "sync_z": 0.55,
                "geo_vector_z": 0.35,
                "macro_vector_z": 0.3,
                "ridge_reach_z": -0.5,
            },
            "phase_thresholds": [
                {"phase": "S0", "label": "normal_noise", "max_probability": 0.3},
                {"phase": "S1", "label": "local_stress", "max_probability": 0.48},
                {"phase": "S2", "label": "sector_horizon_compression", "max_probability": 0.66},
                {"phase": "S3", "label": "cross_sector_defense", "max_probability": 0.82},
                {"phase": "S4", "label": "forced_repricing_risk", "max_probability": 1.0},
            ],
        }
        score = mod.build_score(current, [], signals)
        self.assertEqual(score["phase"], "WARMUP")
        self.assertIsNone(score["probability"])
        self.assertGreater(score["raw_probability"], 0)

    def test_corporate_deformation_can_create_phase_when_gates_met(self):
        evidence = []
        for i in range(3):
            evidence.append({
                "source_type": "news",
                "entity": f"COMPANY_{i}",
                "sector": "retail" if i < 2 else "autos",
                "metadata": {"domain": f"source{i}.com"},
                "classification": {
                    "dust_cloud": 1.0,
                    "defensive_decay": 1.0,
                    "ridge_reach": 0,
                    "geo_vector": 0,
                    "macro_vector": 0,
                },
                "classes": ["dust_cloud", "defensive_decay"],
            })
        current = mod.aggregate_current(evidence)
        self.assertGreaterEqual(current["sync_evidence_count"], 3)
        self.assertGreaterEqual(current["corporate_deformation_count"], 3)
        signals = {
            "min_history_points_for_baseline": 24,
            "min_sync_evidence_for_phase": 3,
            "min_corporate_deformation_evidence_for_phase": 2,
            "require_nonzero_dust_or_decay_for_phase": True,
            "probability": {"intercept": -0.35, "dust_cloud_z": 0.9, "defensive_decay_z": 0.7, "sync_z": 0.55},
            "phase_thresholds": [
                {"phase": "S0", "label": "normal_noise", "max_probability": 0.3},
                {"phase": "S4", "label": "forced_repricing_risk", "max_probability": 1.0},
            ],
        }
        score = mod.build_score(current, [], signals)
        self.assertNotEqual(score["phase"], "WARMUP")
        self.assertIsNotNone(score["probability"])

    def test_gdelt_combined_query_preferred(self):
        signals = {
            "gdelt_combined_query": {
                "name": "one_call",
                "query": "bankruptcy company",
                "timespan": "24h",
                "maxrecords": 10,
            },
            "gdelt_queries": [{"name": "old", "query": "war"}],
        }
        q = mod.gdelt_query_from_config(signals)
        self.assertEqual(q["name"], "one_call")
        self.assertEqual(q["query"], "bankruptcy company")

    def test_dominant_class(self):
        self.assertEqual(mod.dominant_class({"dust_cloud": 0, "defensive_decay": 2, "ridge_reach": 1}), "defensive_decay")
        self.assertEqual(mod.dominant_class({"dust_cloud": 0, "defensive_decay": 0}), "news")


if __name__ == "__main__":
    unittest.main()
