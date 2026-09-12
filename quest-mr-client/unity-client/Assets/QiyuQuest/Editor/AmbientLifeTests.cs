using System;
using System.Collections.Generic;
using System.Text;
using Qiyu.Quest.Behavior;
using UnityEditor;
using UnityEngine;

namespace Qiyu.Quest.Editor
{
    /// <summary>
    /// Ambient Life 策略层的自动测试（用 Unity 自己的编译器跑，无需 .NET SDK）。
    ///
    /// 运行方式：
    ///   Unity.exe -batchmode -quit -projectPath &lt;proj&gt; \
    ///     -executeMethod Qiyu.Quest.Editor.AmbientLifeTests.RunAll
    /// 失败时以退出码 1 结束，成功输出 ALL PASS (n)。
    /// </summary>
    public static class AmbientLifeTests
    {
        private static readonly List<string> Failures = new List<string>();

        public static void RunAll()
        {
            Failures.Clear();
            var cases = new List<Action>
            {
                TestInitializes,
                TestBreathingRunsContinuously,
                TestBlinkContinuesDuringIdle,
                TestGazeChangesSmoothly,
                TestGazeFollowsUserAttention,
                TestMicroMovementHasCooldown,
                TestIdleFidgetDoesNotSpam,
                TestAmbientCannotInterruptExplicitBehavior,
                TestBehaviorCompletionRestoresAmbient,
                TestActivityAffectsAmbientFrequency,
                TestLongIdleProducesLowEnergy,
                TestHighActivityProducesMoreMovement,
                TestTwentySecondsIdleKeepsLiving,
                TestPersonalityProfileChangesBehaviour,
                TestDeterministicWithSameSeed,
            };
            foreach (var caseAction in cases)
            {
                Run(caseAction);
            }
            if (Failures.Count > 0)
            {
                Debug.Log($"AMBIENT TESTS FAILED ({Failures.Count}):\n" +
                          string.Join("\n", Failures));
                EditorApplication.Exit(1);
                return;
            }
            Debug.Log($"AMBIENT ALL PASS ({cases.Count})");
            EditorApplication.Exit(0);
        }

        private static void Run(Action caseAction)
        {
            var name = caseAction.Method.Name;
            Debug.Log($"RUN {name}");
            try
            {
                caseAction();
                Debug.Log($"PASS {name}");
            }
            catch (Exception e)
            {
                Failures.Add($"{name}: {e.Message}");
                Debug.Log($"FAIL {name}: {e.Message}");
            }
        }

        private static void Assert(bool condition, string message)
        {
            if (!condition)
            {
                throw new Exception(message);
            }
        }

        private static AmbientContext IdleContext(float idleSeconds = 0f)
        {
            return new AmbientContext
            {
                userPresent = true,
                userDistance = 1.4f,
                userIdleSeconds = idleSeconds,
            };
        }

        private static void Tick(AmbientLifeCore core, float seconds,
                                 AmbientContext ctx, float step = 1f / 20f,
                                 Action<AmbientFrame> observe = null)
        {
            var elapsed = 0f;
            while (elapsed < seconds)
            {
                var frame = core.Tick(step, ctx);
                observe?.Invoke(frame);
                elapsed += step;
            }
        }

        // ------------------------------------------------------------------ 用例
        private static void TestInitializes()
        {
            var core = new AmbientLifeCore();
            Assert(core.Profile != null, "缺少 personality profile");
            Assert(core.Activity > 0f && core.Activity <= 1f, "activity 未初始化");
            var frame = core.Tick(1f / 20f, IdleContext());
            Assert(frame.activity > 0f, "首帧没有 activity");
            Assert(!string.IsNullOrEmpty(core.DebugLine()), "DebugLine 为空");
        }

        private static void TestBreathingRunsContinuously()
        {
            var core = new AmbientLifeCore();
            var phases = new HashSet<int>();
            var moved = 0f;
            var last = 0f;
            Tick(core, 30f, IdleContext(), 1f / 20f, frame =>
            {
                phases.Add(frame.breathPhase);
                if (Math.Abs(frame.breathChestPitchDeg - last) > 0.0005f)
                {
                    moved += 1f;
                }
                last = frame.breathChestPitchDeg;
            });
            Assert(phases.Count >= 3, $"呼吸相位没有走完（只出现 {phases.Count} 种）");
            Assert(moved > 20f, "呼吸幅度几乎不动");
        }

        private static void TestBlinkContinuesDuringIdle()
        {
            var core = new AmbientLifeCore();
            var blinks = 0;
            var wasClosed = false;
            Tick(core, 40f, IdleContext(), 1f / 20f, frame =>
            {
                var closed = frame.blinkWeight > 0.5f;
                if (closed && !wasClosed)
                {
                    blinks++;
                }
                wasClosed = closed;
            });
            Assert(blinks >= 3, $"40 秒只眨了 {blinks} 次");
            Assert(blinks <= 25, $"眨眼过于频繁：{blinks} 次/40 秒");
        }

        private static void TestGazeChangesSmoothly()
        {
            var core = new AmbientLifeCore();
            var previous = 0f;
            var maxJump = 0f;
            var changes = 0;
            Tick(core, 60f, IdleContext(120f), 1f / 20f, frame =>
            {
                var yaw = frame.gazeYawDeg;
                var jump = Math.Abs(yaw - previous);
                if (jump > maxJump)
                {
                    maxJump = jump;
                }
                if (jump > 0.05f)
                {
                    changes++;
                }
                previous = yaw;
            });
            Assert(changes > 50, "视线几乎没有变化");
            Assert(maxJump < 6f, $"视线跳变过大：{maxJump:F2}°/步");
        }

        private static void TestGazeFollowsUserAttention()
        {
            var core = new AmbientLifeCore();
            var distracted = 0;
            var ctx = IdleContext();
            ctx.userSpeaking = true;
            ctx.userLookingAtAvatar = true;
            ctx.conversationActive = true;
            Tick(core, 12f, ctx, 1f / 20f, frame =>
            {
                if (frame.gazeTarget != 1)
                {
                    distracted++;
                }
            });
            Assert(core.Attention > 0.7f, $"用户说话时注意力没有上升：{core.Attention:F2}");
            Assert(distracted < 40, $"高注意力时移开视线过多（{distracted} 帧）");
        }

        private static void TestMicroMovementHasCooldown()
        {
            var core = new AmbientLifeCore();
            var starts = new List<float>();
            string last = "";
            Tick(core, 120f, IdleContext(60f), 1f / 20f, frame =>
            {
                if (!string.IsNullOrEmpty(frame.ambientAction) &&
                    frame.ambientAction != last &&
                    frame.ambientAction.StartsWith("micro_"))
                {
                    starts.Add(core.Time);
                }
                last = frame.ambientAction;
            });
            Assert(starts.Count >= 1, "两分钟内没有出现任何微动作");
            for (var i = 1; i < starts.Count; i++)
            {
                var gap = starts[i] - starts[i - 1];
                Assert(gap >= 3f, $"微动作间隔过短：{gap:F2}s（冷却失效）");
            }
        }

        private static void TestIdleFidgetDoesNotSpam()
        {
            var core = new AmbientLifeCore();
            var idleStarts = new List<float>();
            string last = "";
            Tick(core, 600f, IdleContext(300f), 1f / 20f, frame =>
            {
                var action = frame.ambientAction;
                if (!string.IsNullOrEmpty(action) &&
                    (action == "stretch" || action == "yawn" ||
                     action == "look_around" || action == "weight_shift") &&
                    action != last)
                {
                    idleStarts.Add(core.Time);
                }
                last = action;
            });
            Assert(idleStarts.Count <= 12,
                   $"10 分钟 idle 动作次数过多：{idleStarts.Count}");
        }

        private static void TestAmbientCannotInterruptExplicitBehavior()
        {
            var core = new AmbientLifeCore();
            core.NotifyExplicitBehavior("wave", 80f, 2f);
            var suppressed = 0;
            var frames = 0;
            Tick(core, 1.8f, IdleContext(60f), 1f / 20f, frame =>
            {
                frames++;
                if (frame.explicitBehaviorActive && string.IsNullOrEmpty(frame.ambientAction))
                {
                    suppressed++;
                }
            });
            Assert(suppressed == frames, "显式行为期间仍在播放 ambient 动作");
            Assert(core.ExplicitBehaviorActive, "显式行为状态没有生效");
        }

        private static void TestBehaviorCompletionRestoresAmbient()
        {
            var core = new AmbientLifeCore();
            core.NotifyExplicitBehavior("wave", 80f, 1f);
            Tick(core, 1.1f, IdleContext(60f), 1f / 20f);
            core.NotifyBehaviorComplete("wave");
            Assert(core.RecoveryActive, "行为结束后没有进入恢复阶段");
            var recovered = false;
            Tick(core, 3f, IdleContext(60f), 1f / 20f, frame =>
            {
                if (!frame.explicitBehaviorActive && !frame.recoveryActive)
                {
                    recovered = true;
                }
            });
            Assert(recovered, "恢复阶段没有结束");
            Assert(!core.ExplicitBehaviorActive, "恢复后仍处于压制状态");
        }

        private static void TestActivityAffectsAmbientFrequency()
        {
            // 同一 seed 下，活跃上下文的微动作次数应多于沉默上下文
            var lively = new AmbientLifeCore(null, 4242);
            var quiet = new AmbientLifeCore(null, 4242);
            var livelyCtx = IdleContext(0f);
            livelyCtx.conversationActive = true;
            livelyCtx.userSpeaking = true;
            livelyCtx.userLookingAtAvatar = true;
            var quietCtx = IdleContext(240f);
            var livelyCount = CountMicroStarts(lively, 90f, livelyCtx);
            var quietCount = CountMicroStarts(quiet, 90f, quietCtx);
            Assert(lively.Activity > quiet.Activity,
                   $"活跃/沉默的 activity 没有区分：{lively.Activity:F2} vs {quiet.Activity:F2}");
            Assert(livelyCount >= quietCount,
                   $"高活动没有带来更多微动作：{livelyCount} vs {quietCount}");
        }

        private static int CountMicroStarts(AmbientLifeCore core, float seconds,
                                            AmbientContext ctx)
        {
            var count = 0;
            string last = "";
            Tick(core, seconds, ctx, 1f / 20f, frame =>
            {
                var action = frame.ambientAction;
                if (!string.IsNullOrEmpty(action) && action != last &&
                    action.StartsWith("micro_"))
                {
                    count++;
                }
                last = action;
            });
            return count;
        }

        private static void TestLongIdleProducesLowEnergy()
        {
            var core = new AmbientLifeCore();
            Tick(core, 240f, IdleContext(300f), 1f / 20f);
            Assert(core.Activity < 0.45f, $"长时间沉默 activity 仍然很高：{core.Activity:F2}");
            Assert(core.Relaxation > 0.4f, $"长时间沉默没有放松：{core.Relaxation:F2}");
        }

        private static void TestHighActivityProducesMoreMovement()
        {
            var core = new AmbientLifeCore();
            var ctx = IdleContext(0f);
            ctx.conversationActive = true;
            ctx.userSpeaking = true;
            ctx.explicitBehaviorActive = true;
            ctx.explicitBehaviorPriority = 30f;
            Tick(core, 20f, ctx, 1f / 20f);
            Assert(core.Activity > 0.6f, $"交互时 activity 没有升高：{core.Activity:F2}");
        }

        private static void TestTwentySecondsIdleKeepsLiving()
        {
            var core = new AmbientLifeCore();
            var breathValues = new HashSet<int>();
            var blinkSeen = false;
            var microSeen = false;
            var gazeMoved = 0f;
            var postureChanges = 0;
            var lastPosture = core.PostureState;
            var lastGaze = 0f;
            Tick(core, 20f, IdleContext(20f), 1f / 20f, frame =>
            {
                breathValues.Add(frame.breathPhase);
                if (frame.blinkWeight > 0.3f)
                {
                    blinkSeen = true;
                }
                if (!string.IsNullOrEmpty(frame.ambientAction))
                {
                    microSeen = true;
                }
                gazeMoved += Math.Abs(frame.gazeYawDeg - lastGaze);
                lastGaze = frame.gazeYawDeg;
                if (frame.postureState != lastPosture)
                {
                    postureChanges++;
                    lastPosture = frame.postureState;
                }
            });
            Assert(breathValues.Count >= 2, "20 秒内呼吸相位没有变化");
            Assert(blinkSeen, "20 秒内没有眨眼");
            Assert(gazeMoved > 5f, "20 秒内视线几乎没动");
            Assert(microSeen, "20 秒内没有任何 ambient 微动作");
            // 20 秒内重心不一定变化（间隔 17~51 秒），这里只要求不异常频繁
            Assert(postureChanges <= 3, $"重心变化过于频繁：{postureChanges}");
        }

        private static void TestPersonalityProfileChangesBehaviour()
        {
            var calm = new AmbientLifeCore(PersonalityMotionProfile.Calm(), 777);
            var lively = new AmbientLifeCore(PersonalityMotionProfile.Lively(), 777);
            var calmCount = CountMicroStarts(calm, 120f, IdleContext(60f));
            var livelyCount = CountMicroStarts(lively, 120f, IdleContext(60f));
            Assert(livelyCount > calmCount,
                   $"性格档案没有影响动作频率：lively={livelyCount} calm={calmCount}");
        }

        private static void TestDeterministicWithSameSeed()
        {
            var a = new AmbientLifeCore(null, 1234);
            var b = new AmbientLifeCore(null, 1234);
            var sumA = 0f;
            var sumB = 0f;
            Tick(a, 15f, IdleContext(30f), 1f / 20f, f => sumA += f.gazeYawDeg + f.blinkWeight);
            Tick(b, 15f, IdleContext(30f), 1f / 20f, f => sumB += f.gazeYawDeg + f.blinkWeight);
            Assert(Math.Abs(sumA - sumB) < 0.001f, "相同 seed 结果不一致");
            var c = new AmbientLifeCore(null, 999);
            var sumC = 0f;
            Tick(c, 15f, IdleContext(30f), 1f / 20f, f => sumC += f.gazeYawDeg + f.blinkWeight);
            Assert(Math.Abs(sumA - sumC) > 0.001f, "不同 seed 结果完全相同");
        }
    }
}
