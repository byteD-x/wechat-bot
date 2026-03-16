from backend.core.emotion import parse_emotion_ai_response


def test_parse_emotion_ai_response_non_object_returns_none():
    assert parse_emotion_ai_response("[]") is None
    assert parse_emotion_ai_response("null") is None

