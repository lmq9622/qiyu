"""P0 Gateway 轻量测试运行器（stdlib，无 pytest 依赖）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_gateway import (  # noqa: E402
    test_first_message_must_be_hello,
    test_hello_heartbeat_echo_and_bye,
    test_user_text_without_brain_returns_honest_error,
    test_world_state_is_stored_and_acked,
)


def main() -> int:
    cases = [
        test_hello_heartbeat_echo_and_bye,
        test_world_state_is_stored_and_acked,
        test_first_message_must_be_hello,
        test_user_text_without_brain_returns_honest_error,
    ]
    for case in cases:
        print(f"RUN {case.__name__}")
        case()
        print(f"PASS {case.__name__}")
    print(f"ALL PASS ({len(cases)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
