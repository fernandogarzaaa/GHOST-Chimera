"""Unit tests for Mixture of Agents."""

import unittest

from ghostchimera.chimera_pilot.mixture_of_agents import MixtureOfAgents, MoAConfig


class MoAConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = MoAConfig()
        self.assertEqual(cfg.num_agents, 3)
        self.assertEqual(cfg.temperature, 0.7)
        self.assertEqual(cfg.min_consensus_pct, 60.0)
        self.assertEqual(cfg.timeout, 120.0)
        self.assertEqual(cfg.voting_strategy, "majority")

    def test_custom_values(self):
        cfg = MoAConfig(num_agents=5, temperature=0.9, min_consensus_pct=80.0, timeout=60.0)
        self.assertEqual(cfg.num_agents, 5)
        self.assertEqual(cfg.temperature, 0.9)
        self.assertEqual(cfg.min_consensus_pct, 80.0)
        self.assertEqual(cfg.timeout, 60.0)


class MixtureOfAgentTests(unittest.TestCase):
    def test_init(self):
        moa = MixtureOfAgents()
        self.assertEqual(moa.config.num_agents, 3)

    def test_init_with_custom_config(self):
        cfg = MoAConfig(num_agents=5)
        moa = MixtureOfAgents(config=cfg)
        self.assertEqual(moa.config.num_agents, 5)

    def test_score_output_float_range(self):
        moa = MixtureOfAgents()
        score = moa.score_output("The answer is 42.", "What is the answer?")
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_score_output_specificity(self):
        moa = MixtureOfAgents()
        # More numbers = higher specificity score
        score1 = moa.score_output("The API returns 429 on rate limit.", "API rate limiting")
        score2 = moa.score_output("The API returns 429 on rate limit. Also returns 500 on error.", "API rate limiting")
        self.assertGreaterEqual(score2, score1)

    def test_score_output_hedging_penalty(self):
        moa = MixtureOfAgents()
        hedged = moa.score_output("I think maybe possibly the answer might be 42.", "What is the answer?")
        direct = moa.score_output("The answer is 42.", "What is the answer?")
        self.assertLessEqual(hedged, direct)

    def test_jaccard_similarity_same(self):
        moa = MixtureOfAgents()
        jacc = moa._jaccard_similarity("hello world", "hello world")
        self.assertEqual(jacc, 1.0)

    def test_jaccard_similarity_disjoint(self):
        moa = MixtureOfAgents()
        jacc = moa._jaccard_similarity("hello world", "goodbye moon")
        self.assertEqual(jacc, 0.0)

    def test_jaccard_similarity_partial(self):
        moa = MixtureOfAgents()
        jacc = moa._jaccard_similarity("hello world", "hello there")
        self.assertGreater(jacc, 0.0)
        self.assertLess(jacc, 1.0)

    def test_jaccard_similarity_empty(self):
        moa = MixtureOfAgents()
        jacc = moa._jaccard_similarity("", "hello")
        self.assertEqual(jacc, 0.0)

    def test_status(self):
        moa = MixtureOfAgents()
        status = moa.status()
        self.assertIn("num_agents", status)
        self.assertIn("voting_strategy", status)
        self.assertIn("min_consensus_pct", status)
        self.assertIn("run_count", status)


if __name__ == "__main__":
    unittest.main()
