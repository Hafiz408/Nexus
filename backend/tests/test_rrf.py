from app.retrieval.graph_rag import rrf_merge


def test_single_list_scores_match_rrf_formula():
    results = [("nodeA", 0.9), ("nodeB", 0.7), ("nodeC", 0.5)]
    scores = rrf_merge([results])
    assert abs(scores["nodeA"] - 1 / 61) < 1e-9
    assert abs(scores["nodeB"] - 1 / 62) < 1e-9
    assert abs(scores["nodeC"] - 1 / 63) < 1e-9


def test_two_lists_same_node_sums_contributions():
    list1 = [("nodeA", 0.9), ("nodeB", 0.5)]
    list2 = [("nodeA", 0.8), ("nodeC", 0.3)]
    scores = rrf_merge([list1, list2])
    assert abs(scores["nodeA"] - (1 / 61 + 1 / 61)) < 1e-9
    assert abs(scores["nodeB"] - 1 / 62) < 1e-9
    assert abs(scores["nodeC"] - 1 / 62) < 1e-9


def test_node_shared_across_lists_beats_single_list_node():
    list1 = [("shared", 0.5), ("solo", 0.9)]
    list2 = [("shared", 0.5)]
    scores = rrf_merge([list1, list2])
    assert scores["shared"] > scores["solo"]


def test_empty_input_returns_empty():
    assert rrf_merge([]) == {}
    assert rrf_merge([[]]) == {}


def test_custom_k_affects_scores():
    results = [("nodeA", 1.0)]
    assert abs(rrf_merge([results], k=60)["nodeA"] - 1 / 61) < 1e-9
    assert abs(rrf_merge([results], k=10)["nodeA"] - 1 / 11) < 1e-9


def test_three_lists_cumulative():
    l1 = [("X", 1.0)]
    l2 = [("X", 0.9)]
    l3 = [("X", 0.8)]
    scores = rrf_merge([l1, l2, l3])
    expected = 3 * (1 / 61)
    assert abs(scores["X"] - expected) < 1e-9
