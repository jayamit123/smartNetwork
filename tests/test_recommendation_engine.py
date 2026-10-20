
import unittest
from types import SimpleNamespace

from diagnosis.recommendation_engine import generate_recommendations


class TestRecommendationEngine(unittest.TestCase):

    
    def test_dns_recommendations(self):
        diagnosis = SimpleNamespace(
            status="ANALYZED",
            probable_category="DNS_RESOLUTION",
            evidence=["DNS degradation and a failed latest DNS check were observed."],
            correlated_symptoms=["dns_degradation"]
        )

        result = generate_recommendations(diagnosis)

        self.assertIn("DNS", result.root_cause)
        self.assertTrue(result.suggested_fixes)
        self.assertTrue(result.verification_steps)


    def test_insufficient_data(self):
        diagnosis = SimpleNamespace(
            status="INSUFFICIENT_DATA",
            probable_category="Unknown",
            evidence=[],
            correlated_symptoms=[]
        )

        result = generate_recommendations(diagnosis)

        self.assertEqual(
            result.root_cause,
            "Insufficient diagnostic data"
        )

    def test_gateway_recommendations(self):
        diagnosis = SimpleNamespace(
            status="DEGRADED",
            probable_category="Gateway problem",
            evidence=["Gateway unreachable"],
            correlated_symptoms=["Gateway failure"]
        )

        result = generate_recommendations(diagnosis)

        self.assertIn("gateway", result.root_cause.lower())
        self.assertTrue(result.suggested_fixes)


if __name__ == "__main__":
    unittest.main()
