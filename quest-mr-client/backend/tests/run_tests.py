"""P0 Gateway 轻量测试运行器（stdlib，无 pytest 依赖）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.test_behavior import (  # noqa: E402
    test_adapter_failure_marks_action_failed,
    test_bridge_cancel_emits_cancelled_events,
    test_bridge_emits_plan_and_action_messages,
    test_bridge_skips_low_relevance_without_messages,
    test_bridge_tick_emits_events_and_state,
    test_build_context_from_world_and_character_state,
    test_cancel_and_cancel_all,
    test_channel_conflict_queueing_same_channel,
    test_cooldown_blocks_immediate_repeat,
    test_dance_strips_locomotion,
    test_greeting_expands_to_parallel_look_smile_wave,
    test_interaction_priority_interrupts_gesture_channel,
    test_low_relevance_and_noop_return_none,
    test_null_adapter_is_safe,
    test_plan_description_is_readable,
    test_priority_interrupt_preempts_lower_priority_in_same_channel,
    test_shy_is_sequence_look_away_head_down_blush_fidget,
    test_sit_with_user_with_seat_keeps_sequence,
    test_sit_with_user_without_seat_degrades_instead_of_sitting,
    test_tease_happy_angry_embarrassed_comfort_are_defined,
    test_unknown_action_in_runtime_is_recorded_as_failed,
    test_unknown_action_is_rejected_not_forwarded,
    test_unknown_intent_returns_none_but_explicit_actions_work,
    test_walk_look_at_smile_run_in_parallel_and_stop_by_duration,
    test_bridge_emits_plan_and_action_messages,
    test_bridge_skips_low_relevance_without_messages,
    test_bridge_tick_emits_events_and_state,
    test_bridge_cancel_emits_cancelled_events,
    test_build_context_from_world_and_character_state,
    test_llm_behavior_intent_is_accepted_and_unknown_is_dropped,
    test_keyword_hint_produces_behavior_and_plain_talk_does_not,
)
from tests.test_gateway import (  # noqa: E402
    test_autonomy_request_emits_optional_speech,
    test_barge_in_is_acked_and_does_not_drop_session,
    test_binary_frame_roundtrip,
    test_character_state_behavior_state_and_interaction_are_acked,
    test_duplicate_sequence_is_ignored,
    test_human_motion_state_is_stored_without_ack_storm,
    test_user_body_is_stored_without_server_error,
    test_first_message_must_be_hello,
    test_gateway_audio_end_uses_stt_and_runs_turn,
    test_gateway_streams_real_tts_binary_frames,
    test_hello_heartbeat_echo_and_bye,
    test_pcm16_wav_roundtrip_and_resample,
    test_planner_fallback_without_llm_is_honest,
    test_planner_llm_rejects_unknown_spatial_target,
    test_planner_v1_1_goal_schema,
    test_real_tts_to_stt_roundtrip,
    test_user_text_with_brain_emits_speech_and_intents,
    test_user_text_without_brain_returns_honest_error,
    test_vision_detector_json_and_bbox_normalization,
    test_vision_request_closed_loop_reruns_same_question,
    test_world_state_store_and_llm_renderer,
    test_world_state_delta_merges_and_rejects_wrong_base,
    test_world_state_is_stored_and_acked,
)


def main() -> int:
    cases = [
        test_hello_heartbeat_echo_and_bye,
        test_world_state_is_stored_and_acked,
        test_first_message_must_be_hello,
        test_user_text_without_brain_returns_honest_error,
        test_user_text_with_brain_emits_speech_and_intents,
        test_barge_in_is_acked_and_does_not_drop_session,
        test_character_state_behavior_state_and_interaction_are_acked,
        test_world_state_delta_merges_and_rejects_wrong_base,
        test_autonomy_request_emits_optional_speech,
        test_duplicate_sequence_is_ignored,
        test_human_motion_state_is_stored_without_ack_storm,
        test_user_body_is_stored_without_server_error,
        test_planner_v1_1_goal_schema,
        test_world_state_store_and_llm_renderer,
        test_planner_fallback_without_llm_is_honest,
        test_planner_llm_rejects_unknown_spatial_target,
        test_binary_frame_roundtrip,
        test_pcm16_wav_roundtrip_and_resample,
        test_gateway_audio_end_uses_stt_and_runs_turn,
        test_gateway_streams_real_tts_binary_frames,
        test_real_tts_to_stt_roundtrip,
        test_vision_detector_json_and_bbox_normalization,
        test_vision_request_closed_loop_reruns_same_question,
        # ---- Behavior 层 ----
        test_greeting_expands_to_parallel_look_smile_wave,
        test_shy_is_sequence_look_away_head_down_blush_fidget,
        test_tease_happy_angry_embarrassed_comfort_are_defined,
        test_low_relevance_and_noop_return_none,
        test_unknown_intent_returns_none_but_explicit_actions_work,
        test_unknown_action_is_rejected_not_forwarded,
        test_sit_with_user_without_seat_degrades_instead_of_sitting,
        test_sit_with_user_with_seat_keeps_sequence,
        test_dance_strips_locomotion,
        test_walk_look_at_smile_run_in_parallel_and_stop_by_duration,
        test_priority_interrupt_preempts_lower_priority_in_same_channel,
        test_interaction_priority_interrupts_gesture_channel,
        test_channel_conflict_queueing_same_channel,
        test_cooldown_blocks_immediate_repeat,
        test_cancel_and_cancel_all,
        test_adapter_failure_marks_action_failed,
        test_unknown_action_in_runtime_is_recorded_as_failed,
        test_null_adapter_is_safe,
        test_plan_description_is_readable,
        # ---- Behavior 网关桥 ----
        test_bridge_emits_plan_and_action_messages,
        test_bridge_skips_low_relevance_without_messages,
        test_bridge_tick_emits_events_and_state,
        test_bridge_cancel_emits_cancelled_events,
        test_build_context_from_world_and_character_state,
        test_llm_behavior_intent_is_accepted_and_unknown_is_dropped,
        test_keyword_hint_produces_behavior_and_plain_talk_does_not,
    ]
    for case in cases:
        print(f"RUN {case.__name__}")
        case()
        print(f"PASS {case.__name__}")
    print(f"ALL PASS ({len(cases)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




