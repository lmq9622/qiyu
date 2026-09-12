# -*- coding: utf-8 -*-
"""栖语 · Realtime Omni E2E 测试台（规格 §24 / §25）。

两件事：

1. **A–T 二十个用例定义**（规格 §24 原文），每个用例标注
   ``sim``（本地可模拟验证）/ ``quest``（需 Quest 真机）/ ``media``（需 WebRTC）。
2. **REAL_CONVERSATION_TEST 记录器**（规格 §25）：每轮记录

   User Input / World State / Audio / Video / Omni output / AvatarIntent /
   Behavior / Final Avatar action / Latency

   规格式：JSONL，一行一轮，便于人工抽查真实体验。

运行：

```bash
python -m runtime.omni.e2e --quick          # 跑本地可模拟的用例（Mock 后端）
python -m runtime.omni.e2e --list           # 只列用例
```
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from runtime.omni.types import (
    AudioChunk,
    HumanInteractionEvent,
    SessionConfig,
    SpeakerId,
    VideoFrame,
    WorldEvent,
)


@dataclass
class CaseDef:
    key: str
    name: str
    desc: str
    sim: bool = False       # 本地（Mock 后端）可验证编排链路
    quest: bool = False     # 需要 Quest 真机
    media: bool = False     # 需要 WebRTC 媒体面

    def to_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "desc": self.desc,
                "sim": self.sim, "quest": self.quest, "media": self.media}


CASES: tuple = (
    CaseDef("A", "纯语音对话", "麦克风 → 流式 → 文本+语音回复", sim=True),
    CaseDef("B", "连续语音", "不等整句结束，多段 partial 连续进", sim=True),
    CaseDef("C", "视频+语音", "视频帧按调度器进 + 语音", sim=True),
    CaseDef("D", "用户说话中插话", "avatar 说话时用户开口 → 立即停 + cancel", sim=True),
    CaseDef("E", "视觉问题", "“这是啥”类问题需要视觉输入", sim=True),
    CaseDef("F", "指向物体", "用户指向 → 本地 raycast → WorldEvent", sim=True, quest=True),
    CaseDef("G", "用户挥手", "wave 事件 → AvatarIntent=wave", sim=True, quest=True),
    CaseDef("H", "用户招手", "come_here 事件 → AvatarIntent=approach", sim=True, quest=True),
    CaseDef("I", "击掌", "high_five → AvatarIntent=high_five", sim=True, quest=True),
    CaseDef("J", "跟随", "follow 指令 → 持续跟随", sim=True, quest=True),
    CaseDef("K", "空间移动", "Avatar 在房间内移动", sim=False, quest=True),
    CaseDef("L", "视频通话", "WebRTC 建立 + 音视频互通", sim=False, media=True),
    CaseDef("M", "远端声音", "远端音频进 Omni（speaker_id=remote_user）", sim=True, media=True),
    CaseDef("N", "远端视频", "远端关键帧/快照进 Omni", sim=True, media=True),
    CaseDef("O", "AI 同时理解远端视频/声音", "多模态融合", sim=False, media=True),
    CaseDef("P", "WebRTC 断线", "断线重连，媒体面自愈", sim=False, media=True),
    CaseDef("Q", "Omni 断线", "backend 异常 → 上层收到 error 事件", sim=True),
    CaseDef("R", "AI 断开时 Avatar 本地继续", "Omni 不可用时 idle/reflex 仍运行", sim=False, quest=True),
    CaseDef("S", "长时间运行", "长稳：延迟不爬升、内存不泄漏", sim=True),
    CaseDef("T", "多轮上下文", "多轮上下文一致性", sim=True),
)


@dataclass
class TurnRecord:
    """一行 REAL_CONVERSATION_TEST 记录。"""

    case: str = ""
    turn: int = 0
    user_input: dict = field(default_factory=dict)
    world_state: dict = field(default_factory=dict)
    audio: dict = field(default_factory=dict)
    video: dict = field(default_factory=dict)
    omni_output: dict = field(default_factory=dict)
    avatar_intent: list = field(default_factory=list)
    behavior: dict = field(default_factory=dict)     # Behavior Policy 侧，未接 Quest 时为空
    final_avatar_action: dict = field(default_factory=dict)
    latency_ms: dict = field(default_factory=dict)
    notes: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "case": self.case,
            "turn": self.turn,
            "user_input": self.user_input,
            "world_state": self.world_state,
            "audio": self.audio,
            "video": self.video,
            "omni_output": self.omni_output,
            "avatar_intent": self.avatar_intent,
            "behavior": self.behavior,
            "final_avatar_action": self.final_avatar_action,
            "latency_ms": self.latency_ms,
            "notes": self.notes,
            "ts": self.ts,
        }


class ConversationRecorder:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else Path("runtime/omni/out/real_conversation_test.jsonl")
        self.records: list = []

    def add(self, rec: TurnRecord) -> None:
        self.records.append(rec)

    def flush(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            for r in self.records:
                f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
        return self.path


# ---------------------------------------------------------------------------
# 本地可跑的执行器（Mock 后端 / 真实后端都能用）
# ---------------------------------------------------------------------------


def _silence(ms: float = 40.0, speaker: str = SpeakerId.LOCAL_USER.value,
             amp: float = 0.0) -> AudioChunk:
    n = max(1, int(16000 * ms / 1000.0))
    pcm = [amp] * n
    return AudioChunk(pcm=pcm, sample_rate=16000, speaker_id=speaker)


async def _collect(session, seconds: float = 1.2) -> dict:
    """收集一段时间内的输出。"""
    out = {"text": "", "audio": 0, "intents": [], "events": []}
    deadline = time.time() + seconds

    async def _read_events():
        async for ev in session.receive_event():
            if ev.avatar_intent is not None:
                out["intents"].append(ev.avatar_intent.to_wire())
            if ev.conversation is not None:
                if ev.conversation.text:
                    out["text"] += ev.conversation.text
                if ev.conversation.audio is not None:
                    out["audio"] += 1
            if ev.payload:
                out["events"].append(ev.payload.get("event", ""))
            if time.time() > deadline:
                return

    try:
        await asyncio.wait_for(_read_events(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    return out


async def run_quick(recorder: Optional[ConversationRecorder] = None,
                    out_dir: Optional[Path] = None) -> dict:
    """跑 A/B/C/D/E/G/H/I/Q/S/T 这些本地可验证的编排链路。"""
    from runtime.omni import build_omni

    recorder = recorder or ConversationRecorder(out_dir)
    results: dict = {}

    # ---- A 纯语音对话 ----
    sess = build_omni(allow_mock=True)
    await sess.start_session(SessionConfig(personality="栖语", full_duplex=True))
    await sess.send_text("在吗")
    got = await _collect(sess, 0.8)
    results["A"] = {"text": got["text"], "audio_chunks": got["audio"], "ok": bool(got["text"])}
    recorder.add(TurnRecord(case="A", turn=1, user_input={"text": "在吗"},
                            omni_output={"text": got["text"]},
                            latency_ms=sess.metrics.report()["facts"],
                            notes="纯语音对话（Mock 编排链路）"))
    await sess.close()

    # ---- B 连续语音（不等整句） ----
    sess = build_omni(allow_mock=True)
    await sess.start_session(SessionConfig())
    for _ in range(5):
        await sess.send_audio_chunk(_silence(40, amp=0.05))
    results["B"] = {"audio_in": sess.counters["audio_in"], "ok": sess.counters["audio_in"] == 5}
    await sess.close()

    # ---- C 视频+语音（调度器降采样） ----
    sess = build_omni(allow_mock=True)
    await sess.start_session(SessionConfig())
    await sess.send_text("看看这个")
    for i in range(60):                      # 模拟 60 帧 @30FPS = 2 秒
        await sess.send_video_frame(VideoFrame(data=f"f{i}", frame_id=i))
        await asyncio.sleep(0.033)
    snap = sess.video.snapshot()
    results["C"] = {"offered": snap["offered"], "sent": snap["sent"],
                    "dropped": snap["dropped"], "effective_fps": snap["effective_fps"],
                    "ok": snap["sent"] < snap["offered"]}
    await sess.close()

    # ---- D 插话打断 ----
    # 用「慢速 mock」模拟真实说话过程，否则回复在一帧内就说完了，测不到插话
    from runtime.omni.backends.mock import MockOmniBackend
    from runtime.omni.session import OmniSession as _OmniSession
    sess = _OmniSession(MockOmniBackend(step_ms=30))
    await sess.start_session(SessionConfig())
    await sess.send_text("你给我讲个很长的故事")
    await asyncio.sleep(0.4)                        # 让它开始说
    speaking_before = sess._speaking
    for _ in range(3):                              # 累积到 >160ms 才算真正开口
        await sess.send_audio_chunk(_silence(100, amp=0.25))
    results["D"] = {
        "speaking_before": speaking_before,
        "interrupts": sess.counters["interrupts"],
        "interrupt_ms": sess.metrics.report()["facts"].get("interrupt_latency_ms"),
        "ok": sess.counters["interrupts"] >= 1,
    }
    recorder.add(TurnRecord(case="D", turn=1,
                            user_input={"text": "（用户插话）"},
                            audio={"barge_in": True},
                            latency_ms={"interrupt_ms": results["D"]["interrupt_ms"]},
                            notes="avatar 说话中用户开口 → barge-in"))
    await sess.close()

    # ---- E 视觉问题 ----
    sess = build_omni(allow_mock=True)
    await sess.start_session(SessionConfig(topic_state="用户想让我看东西"))
    await sess.send_video_frame(VideoFrame(data="snap", frame_id=1, kind="snapshot"))
    await sess.send_text("你看看这是什么")
    got = await _collect(sess, 0.6)
    results["E"] = {"intents": got["intents"], "ok": bool(got["intents"])}
    await sess.close()

    # ---- G/H/I 动捕事件 → AvatarIntent ----
    for key, evname, want in (("G", "wave", "wave"), ("H", "come_here", "approach"),
                              ("I", "high_five", "high_five")):
        sess = build_omni(allow_mock=True)
        await sess.start_session(SessionConfig())
        await sess.send_motion_event(HumanInteractionEvent(name=evname, confidence=0.9, target="user"))
        got = await _collect(sess, 0.5)
        intents = [i.get("intent") for i in got["intents"]]
        results[key] = {"intents": intents, "ok": want in intents}
        recorder.add(TurnRecord(case=key, turn=1,
                                user_input={"motion": evname},
                                avatar_intent=got["intents"],
                                notes=f"{evname} → {want}"))
        await sess.close()

    # ---- Q Omni 断线 ----
    sess = build_omni(allow_mock=True)
    await sess.start_session(SessionConfig())
    await sess.stream.close()                      # 模拟后端断开
    got = await _collect(sess, 0.5)
    results["Q"] = {"events": got["events"], "ok": "stream_closed" in got["events"]}
    await sess.close()

    # ---- S 长稳（短时抽样） ----
    sess = build_omni(allow_mock=True)
    await sess.start_session(SessionConfig())
    lat = []
    for i in range(20):
        t0 = time.time()
        await sess.send_audio_chunk(_silence(20, amp=0.03))
        lat.append((time.time() - t0) * 1000.0)
    results["S"] = {"n": len(lat), "avg_ms": round(sum(lat) / len(lat), 3),
                    "max_ms": round(max(lat), 3), "ok": max(lat) < 50}
    await sess.close()

    # ---- T 多轮上下文 ----
    sess = build_omni(allow_mock=True)
    await sess.start_session(SessionConfig())
    texts = []
    for t in ("我叫小林", "我养了只猫", "它叫什么好"):
        await sess.send_text(t)
        got = await _collect(sess, 0.5)
        texts.append(got["text"])
    results["T"] = {"turns": len(texts), "texts": texts, "ok": all(texts)}
    await sess.close()

    path = recorder.flush()
    return {"results": results, "record_path": str(path)}


def list_cases() -> str:
    lines = [f"{c.key:>2s}  {c.name:<22s} {'SIM' if c.sim else '   '} "
             f"{'QUEST' if c.quest else '     '} {'MEDIA' if c.media else '     '}  {c.desc}"
             for c in CASES]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="栖语 Realtime Omni E2E")
    ap.add_argument("--list", action="store_true", help="只列用例")
    ap.add_argument("--quick", action="store_true", help="跑本地可模拟的用例")
    ap.add_argument("--out", default="", help="记录输出目录")
    args = ap.parse_args()

    if args.list or not args.quick:
        print(list_cases())
        if not args.quick:
            return 0

    out_dir = Path(args.out) if args.out else None
    rep = asyncio.run(run_quick(out_dir=out_dir))
    print(json.dumps(rep["results"], ensure_ascii=False, indent=2))
    print(f"\nREAL_CONVERSATION_TEST 记录: {rep['record_path']}")
    ok = all(v.get("ok") for v in rep["results"].values())
    print("\n结果:", "PASS" if ok else "PARTIAL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
