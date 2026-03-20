from backend.core.reply_quality_tracker import ReplyQualityTracker


def test_reply_quality_tracker_aggregates_recent_windows(tmp_path):
    tracker = ReplyQualityTracker(str(tmp_path / "reply_quality.db"))

    tracker.log_event(
        outcome="success",
        delayed=True,
        retrieval_augmented=True,
        retrieval_hit_count=3,
        timestamp=2_000_000.0,
    )
    tracker.log_event(
        outcome="empty",
        timestamp=2_000_100.0,
    )
    tracker.log_event(
        outcome="failed",
        timestamp=2_000_200.0,
    )

    recent = tracker.get_summary(since_ts=1_999_999.0)

    assert recent["attempted"] == 3
    assert recent["successful"] == 1
    assert recent["empty"] == 1
    assert recent["failed"] == 1
    assert recent["delayed"] == 1
    assert recent["retrieval_augmented"] == 1
    assert recent["retrieval_hit_count"] == 3
    assert recent["success_rate"] == 33.3


def test_reply_quality_tracker_filters_old_records(tmp_path):
    tracker = ReplyQualityTracker(str(tmp_path / "reply_quality.db"))

    tracker.log_event(outcome="success", timestamp=100.0)
    tracker.log_event(outcome="failed", timestamp=200.0)

    recent = tracker.get_summary(since_ts=150.0)

    assert recent["attempted"] == 1
    assert recent["successful"] == 0
    assert recent["failed"] == 1
    assert recent["success_rate"] == 0.0


def test_reply_quality_tracker_tracks_feedback_windows(tmp_path):
    tracker = ReplyQualityTracker(str(tmp_path / "reply_quality.db"))

    tracker.log_feedback(message_id=1, feedback="helpful", timestamp=300.0)
    tracker.log_feedback(message_id=2, feedback="unhelpful", timestamp=320.0)
    tracker.log_feedback(message_id=2, feedback="helpful", timestamp=340.0)

    recent = tracker.get_summary(since_ts=250.0)

    assert recent["helpful_count"] == 2
    assert recent["unhelpful_count"] == 0
