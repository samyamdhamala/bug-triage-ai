import json
import pytest
from unittest.mock import patch, MagicMock


# --- vector_store helpers ---

class TestBugToText:
    def test_combines_key_fields(self):
        from backend.vector_store import _bug_to_text
        t = {"title": "Login broken", "component": "Auth", "actual_behavior": "500 error", "bug_type": "crash"}
        assert _bug_to_text(t) == "Login broken Auth 500 error crash"

    def test_skips_empty_fields(self):
        from backend.vector_store import _bug_to_text
        t = {"title": "Login broken", "component": "", "actual_behavior": "", "bug_type": ""}
        assert _bug_to_text(t) == "Login broken"

    def test_empty_triage_returns_empty(self):
        from backend.vector_store import _bug_to_text
        assert _bug_to_text({}) == ""


class TestCosineSimilarity:
    def test_identical_vectors_score_one(self):
        from backend.vector_store import cosine_similarity
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        from backend.vector_store import cosine_similarity
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors_score_minus_one(self):
        from backend.vector_store import cosine_similarity
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


class TestFindSimilar:
    def test_returns_none_when_store_empty(self):
        from backend.vector_store import find_similar
        with patch("backend.vector_store._load_store", return_value=[]):
            result = find_similar({"title": "crash", "component": "auth"})
        assert result is None

    def test_returns_none_when_triage_has_no_text(self):
        from backend.vector_store import find_similar
        with patch("backend.vector_store._load_store", return_value=[{"embedding": [1.0, 0.0]}]):
            result = find_similar({})
        assert result is None

    def test_returns_match_above_threshold(self):
        from backend.vector_store import find_similar
        embedding = [1.0, 0.0, 0.0]
        store = [{"jira_key": "BT-1", "jira_url": "https://x/BT-1", "title": "Login broken", "embedding": embedding}]
        with patch("backend.vector_store._load_store", return_value=store), \
             patch("backend.vector_store.embed_text", return_value=embedding):
            result = find_similar({"title": "Login broken", "component": "", "actual_behavior": "", "bug_type": ""})
        assert result is not None
        assert result["jira_key"] == "BT-1"
        assert result["similarity"] == 100.0

    def test_returns_none_below_threshold(self):
        from backend.vector_store import find_similar
        store = [{"jira_key": "BT-1", "jira_url": "https://x/BT-1", "title": "Login broken", "embedding": [0.0, 1.0, 0.0]}]
        with patch("backend.vector_store._load_store", return_value=store), \
             patch("backend.vector_store.embed_text", return_value=[1.0, 0.0, 0.0]):
            result = find_similar({"title": "Payment timeout", "component": "", "actual_behavior": "", "bug_type": ""})
        assert result is None


# --- find_similar_in_jira ---

class TestFindSimilarInJira:
    def _make_issues(self, summaries):
        return [{"key": f"BT-{i+1}", "fields": {"summary": s}} for i, s in enumerate(summaries)]

    def test_returns_none_on_jira_api_error(self):
        from backend.jira_client import find_similar_in_jira
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("backend.jira_client.requests.post", return_value=mock_resp), \
             patch.dict("os.environ", {"JIRA_BASE_URL": "https://x", "JIRA_EMAIL": "a@b.com",
                                       "JIRA_API_TOKEN": "tok", "JIRA_PROJECT_KEY": "BT"}):
            result = find_similar_in_jira({"title": "Login broken"})
        assert result is None

    def test_returns_none_when_no_issues(self):
        from backend.jira_client import find_similar_in_jira
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issues": []}
        with patch("backend.jira_client.requests.post", return_value=mock_resp), \
             patch.dict("os.environ", {"JIRA_BASE_URL": "https://x", "JIRA_EMAIL": "a@b.com",
                                       "JIRA_API_TOKEN": "tok", "JIRA_PROJECT_KEY": "BT"}):
            result = find_similar_in_jira({"title": "Login broken"})
        assert result is None

    def test_returns_match_above_threshold(self):
        from backend.jira_client import find_similar_in_jira
        import numpy as np

        issues = self._make_issues(["Login button broken"])
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issues": issues}

        identical_embedding = [1.0, 0.0, 0.0]
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([identical_embedding])

        with patch("backend.jira_client.requests.post", return_value=mock_resp), \
             patch("backend.vector_store.embed_text", return_value=identical_embedding), \
             patch("backend.vector_store._get_model", return_value=mock_model), \
             patch("backend.vector_store._bug_to_text", return_value="Login button broken"), \
             patch.dict("os.environ", {"JIRA_BASE_URL": "https://x", "JIRA_EMAIL": "a@b.com",
                                       "JIRA_API_TOKEN": "tok", "JIRA_PROJECT_KEY": "BT"}):
            result = find_similar_in_jira({"title": "Login button broken"})

        assert result is not None
        assert result["key"] == "BT-1"
        assert result["similarity"] == 100.0

    def test_returns_none_below_threshold(self):
        from backend.jira_client import find_similar_in_jira
        import numpy as np

        issues = self._make_issues(["Unrelated issue about exports"])
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issues": issues}

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.0, 1.0, 0.0]])

        with patch("backend.jira_client.requests.post", return_value=mock_resp), \
             patch("backend.vector_store.embed_text", return_value=[1.0, 0.0, 0.0]), \
             patch("backend.vector_store._get_model", return_value=mock_model), \
             patch("backend.vector_store._bug_to_text", return_value="Login button broken"), \
             patch.dict("os.environ", {"JIRA_BASE_URL": "https://x", "JIRA_EMAIL": "a@b.com",
                                       "JIRA_API_TOKEN": "tok", "JIRA_PROJECT_KEY": "BT"}):
            result = find_similar_in_jira({"title": "Login button broken"})

        assert result is None

    def test_returns_none_when_triage_has_no_text(self):
        from backend.jira_client import find_similar_in_jira
        issues = self._make_issues(["Login broken"])
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"issues": issues}

        with patch("backend.jira_client.requests.post", return_value=mock_resp), \
             patch("backend.vector_store._bug_to_text", return_value=""), \
             patch.dict("os.environ", {"JIRA_BASE_URL": "https://x", "JIRA_EMAIL": "a@b.com",
                                       "JIRA_API_TOKEN": "tok", "JIRA_PROJECT_KEY": "BT"}):
            result = find_similar_in_jira({})

        assert result is None
