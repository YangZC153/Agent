import unittest
from datetime import date

from monitor import (
    build_screening_pool,
    extract_json_object,
    paper_is_recent,
    paper_matches_topic,
    search_and_select_new_papers,
    select_topic_papers,
)
import monitor


TOPICS = [
    {"id": 1, "name": "T1", "target_quota": 6, "ranking_terms": ["topic one"]},
    {"id": 2, "name": "T2", "target_quota": 1, "ranking_terms": ["topic two"]},
    {"id": 3, "name": "T3", "target_quota": 1, "ranking_terms": ["topic three"]},
    {"id": 4, "name": "T4", "target_quota": 1, "ranking_terms": ["topic four"]},
    {"id": 5, "name": "T5", "target_quota": 1, "ranking_terms": ["topic five"]},
]


def paper(arxiv_id, topic_number, published_date="2026-06-09"):
    return {
        "arxiv_id": arxiv_id,
        "title": f"Topic {topic_number} paper {arxiv_id}",
        "summary": f"This abstract studies topic {topic_number}.",
        "published_date": published_date,
    }


class SelectTopicPapersTests(unittest.TestCase):
    def test_uses_six_one_one_one_one_target(self):
        candidates = {
            topic_id: [paper(f"{topic_id}.{index}", topic_id) for index in range(8)]
            for topic_id in range(1, 6)
        }

        selected = select_topic_papers(candidates, TOPICS, limit=10)

        counts = {
            topic_id: sum(item["topic_id"] == topic_id for item in selected)
            for topic_id in range(1, 6)
        }
        self.assertEqual(len(selected), 10)
        self.assertEqual(counts, {1: 6, 2: 1, 3: 1, 4: 1, 5: 1})

    def test_deduplicates_overlapping_topic_results(self):
        shared = paper("shared", 1)
        candidates = {
            1: [shared, paper("1.1", 1)],
            2: [shared, paper("2.1", 2)],
            3: [paper("3.1", 3)],
            4: [paper("4.1", 4)],
            5: [paper("5.1", 5)],
        }

        selected = select_topic_papers(candidates, TOPICS, limit=5)

        ids = [item["arxiv_id"] for item in selected]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({item["topic_id"] for item in selected}, {1, 2, 3, 4, 5})

    def test_returns_available_count_when_fewer_than_limit(self):
        candidates = {
            1: [paper("1.1", 1)],
            2: [],
            3: [paper("3.1", 3)],
            4: [],
            5: [],
        }

        selected = select_topic_papers(candidates, TOPICS, limit=10)

        self.assertEqual([item["arxiv_id"] for item in selected], ["1.1", "3.1"])

    def test_unused_topic_one_quota_rolls_forward_to_topic_two(self):
        candidates = {
            1: [paper("1.1", 1), paper("1.2", 1)],
            2: [paper(f"2.{index}", 2) for index in range(10)],
            3: [paper("3.1", 3)],
            4: [paper("4.1", 4)],
            5: [paper("5.1", 5)],
        }

        selected = select_topic_papers(candidates, TOPICS, limit=10)

        counts = {
            topic_id: sum(item["topic_id"] == topic_id for item in selected)
            for topic_id in range(1, 6)
        }
        self.assertEqual(counts, {1: 2, 2: 5, 3: 1, 4: 1, 5: 1})

    def test_never_exceeds_limit(self):
        candidates = {
            topic_id: [paper(f"{topic_id}.{index}", topic_id) for index in range(8)]
            for topic_id in range(1, 6)
        }

        selected = select_topic_papers(candidates, TOPICS, limit=3)

        self.assertEqual(len(selected), 3)
        self.assertEqual([item["topic_id"] for item in selected], [1, 2, 3])

    def test_required_term_groups_filter_unrelated_papers(self):
        topic = {
            "required_term_groups": [
                ["agentic", "llm agent"],
                ["recommender system", "recommendation system"],
            ]
        }
        relevant = {
            "title": "An Agentic Recommender System",
            "summary": "An LLM agent improves personalized ranking.",
        }
        unrelated = {
            "title": "Agent Memory for Software Engineering",
            "summary": "The system offers general workflow recommendations.",
        }

        self.assertTrue(paper_matches_topic(relevant, topic))
        self.assertFalse(paper_matches_topic(unrelated, topic))

    def test_recent_window_allows_backfill_but_not_stale_papers(self):
        today = date(2026, 6, 9)

        self.assertTrue(
            paper_is_recent({"published_date": "2026-05-10"}, today=today)
        )
        self.assertFalse(
            paper_is_recent({"published_date": "2026-05-09"}, today=today)
        )

    def test_open_source_papers_rank_first_within_topic(self):
        closed = paper("1.closed", 1, published_date="2026-06-09")
        closed["screening_score"] = 99
        closed["code_open_source"] = "摘要未说明"
        opened = paper("1.open", 1, published_date="2026-06-08")
        opened["screening_score"] = 80
        opened["code_open_source"] = "是"

        selected = select_topic_papers({1: [closed, opened]}, TOPICS[:1], limit=1)

        self.assertEqual(selected[0]["arxiv_id"], "1.open")

    def test_screening_pool_deduplicates_cross_topic_candidates(self):
        shared = paper("shared", 1)
        pool = build_screening_pool(
            {1: [shared], 2: [shared], 3: [], 4: [], 5: []},
            TOPICS,
        )

        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0]["candidate_topic_ids"], [1, 2])

    def test_extract_json_object_accepts_code_fence(self):
        payload = extract_json_object(
            '```json\n{"papers":[{"arxiv_id":"1"}]}\n```'
        )

        self.assertEqual(payload["papers"][0]["arxiv_id"], "1")

    def test_search_retries_failed_topic_before_screening(self):
        topics = [{
            "id": 1,
            "name": "T1",
            "target_quota": 1,
            "query": "q1",
            "ranking_terms": ["topic one"],
        }]
        calls = {"q1": 0}
        original_search = monitor.search_arxiv_papers
        original_screen = monitor.screen_candidates_with_deepseek
        original_sleep = monitor.time.sleep
        original_retry_rounds = monitor.ARXIV_FAILED_TOPIC_RETRY_ROUNDS
        original_retry_delay = monitor.ARXIV_FAILED_TOPIC_RETRY_DELAY
        try:
            monitor.ARXIV_FAILED_TOPIC_RETRY_ROUNDS = 1
            monitor.ARXIV_FAILED_TOPIC_RETRY_DELAY = 0
            monitor.time.sleep = lambda _seconds: None

            def fake_search(query):
                calls[query] += 1
                if calls[query] == 1:
                    raise RuntimeError("temporary arXiv error")
                return [paper("retry.1", 1)]

            def fake_screen(candidates, _topics):
                return [
                    {
                        **candidate,
                        "topic_id": 1,
                        "topic_name": "T1",
                        "screening_score": 90,
                        "code_open_source": "摘要未说明",
                        "code_url": "",
                    }
                    for candidate in candidates
                ]

            monitor.search_arxiv_papers = fake_search
            monitor.screen_candidates_with_deepseek = fake_screen

            selected = search_and_select_new_papers(topics, set(), limit=10)

            self.assertEqual([item["arxiv_id"] for item in selected], ["retry.1"])
            self.assertEqual(calls["q1"], 2)
            self.assertEqual(monitor.LAST_SEARCH_FAILURES, [])
        finally:
            monitor.search_arxiv_papers = original_search
            monitor.screen_candidates_with_deepseek = original_screen
            monitor.time.sleep = original_sleep
            monitor.ARXIV_FAILED_TOPIC_RETRY_ROUNDS = original_retry_rounds
            monitor.ARXIV_FAILED_TOPIC_RETRY_DELAY = original_retry_delay

    def test_search_failure_is_reported_after_retry_exhaustion(self):
        topics = [{
            "id": 1,
            "name": "T1",
            "target_quota": 1,
            "query": "q1",
            "ranking_terms": ["topic one"],
        }]
        original_search = monitor.search_arxiv_papers
        original_sleep = monitor.time.sleep
        original_retry_rounds = monitor.ARXIV_FAILED_TOPIC_RETRY_ROUNDS
        original_retry_delay = monitor.ARXIV_FAILED_TOPIC_RETRY_DELAY
        try:
            monitor.ARXIV_FAILED_TOPIC_RETRY_ROUNDS = 1
            monitor.ARXIV_FAILED_TOPIC_RETRY_DELAY = 0
            monitor.time.sleep = lambda _seconds: None
            monitor.search_arxiv_papers = lambda _query: (_ for _ in ()).throw(
                RuntimeError("persistent arXiv error")
            )

            selected = search_and_select_new_papers(topics, set(), limit=10)

            self.assertEqual(selected, [])
            self.assertEqual(len(monitor.LAST_SEARCH_FAILURES), 1)
            self.assertEqual(monitor.LAST_SEARCH_FAILURES[0]["topic_id"], 1)
        finally:
            monitor.search_arxiv_papers = original_search
            monitor.time.sleep = original_sleep
            monitor.ARXIV_FAILED_TOPIC_RETRY_ROUNDS = original_retry_rounds
            monitor.ARXIV_FAILED_TOPIC_RETRY_DELAY = original_retry_delay


if __name__ == "__main__":
    unittest.main()
