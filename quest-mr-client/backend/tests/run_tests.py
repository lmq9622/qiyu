"""P0 Gateway 轻量测试运行器（stdlib，无 pytest 依赖）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tests.test_gateway import (  # noqa: E402
    test_barge_in_is_acked_and_does_not_drop_session,
    test_binary_frame_roundtrip,
    test_first_message_must_be_hello,
    test_gateway_audio_end_uses_stt_and_runs_turn,
    test_gateway_streams_real_tts_binary_frames,
    test_hello_heartbeat_echo_and_bye,
    test_pcm16_wav_roundtrip_and_resample,
    test_planner_fallback_without_llm_is_honest,
    test_planner_llm_rejects_unknown_spatial_target,
    test_real_tts_to_stt_roundtrip,
    test_user_text_with_brain_emits_speech_and_intents,
    test_user_text_without_brain_returns_honest_error,
    test_vision_detector_json_and_bbox_normalization,
    test_vision_request_closed_loop_reruns_same_question,
    test_world_state_store_and_llm_renderer,
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
    ]
    for case in cases:
        print(f"RUN {case.__name__}")
        case()
        print(f"PASS {case.__name__}")
    print(f"ALL PASS ({len(cases)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
