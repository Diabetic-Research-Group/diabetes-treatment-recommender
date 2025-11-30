from src.recommender.expert_system import DiabetesExpertSystem

def test_recommend_missing_hba1c():
    es = DiabetesExpertSystem()
    out = es.recommend({})
    assert out["confidence"] == 0.0

def test_recommend_high_hba1c():
    es = DiabetesExpertSystem()
    out = es.recommend({"hba1c": 11.0})
    assert "intensive" in out["recommendation"].lower()
