using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace Qiyu.Quest.Behavior
{
    /// <summary>
    /// Ambient Life 策略核心：纯 C#，不依赖 UnityEngine。
    ///
    /// 为什么单独拆出来：这一层是"活着的感觉"的全部策略（呼吸节奏、眨眼类型、
    /// 视线注意、重心变化、微动作调度、idle 动作效用、生命节奏）。拆成纯逻辑后
    /// 可以用 Roslyn 独立编译并在真机之外跑自动测试，MonoBehaviour 只负责把
    /// 输出落到骨骼上。
    ///
    /// 刻意规避的做法：每 N 秒随机播一个动作、纯随机 transform、固定周期正弦。
    /// 采用：随机化周期 + 弹簧阻尼趋近 + 效用评分 + 冷却 + 保持/回归阶段。
    /// </summary>
    public sealed class PersonalityMotionProfile
    {
        public string name = "balanced";
        public float movementFrequency = 1f;
        public float gazeFrequency = 1f;
        public float fidgetFrequency = 1f;
        public float blinkRate = 1f;
        public float postureVariability = 1f;
        public float energy = 0.6f;
        public float restlessness = 0.3f;
        public float socialAttention = 0.7f;

        public static PersonalityMotionProfile Balanced()
        {
            return new PersonalityMotionProfile();
        }

        /// <summary>安静型：动作少、重心变化少、注视偏温和。</summary>
        public static PersonalityMotionProfile Calm()
        {
            return new PersonalityMotionProfile
            {
                name = "calm",
                movementFrequency = 0.55f,
                gazeFrequency = 0.8f,
                fidgetFrequency = 0.4f,
                blinkRate = 0.9f,
                postureVariability = 0.5f,
                energy = 0.45f,
                restlessness = 0.15f,
                socialAttention = 0.75f,
            };
        }

        /// <summary>活泼型：动作多、注视频繁、重心变化明显。</summary>
        public static PersonalityMotionProfile Lively()
        {
            return new PersonalityMotionProfile
            {
                name = "lively",
                movementFrequency = 1.6f,
                gazeFrequency = 1.5f,
                fidgetFrequency = 1.8f,
                blinkRate = 1.15f,
                postureVariability = 1.7f,
                energy = 0.85f,
                restlessness = 0.7f,
                socialAttention = 0.85f,
            };
        }
    }

    /// <summary>Ambient Life 需要的外部上下文（由既有运行时读取后传入）。</summary>
    public struct AmbientContext
    {
        public bool userPresent;
        public float userDistance;
        public bool userSpeaking;
        public bool userLookingAtAvatar;
        public bool userApproaching;
        public float userIdleSeconds;
        public bool conversationActive;
        public bool explicitBehaviorActive;
        public float explicitBehaviorPriority;
        public bool locomotionActive;
        public float locomotionSpeed;
        public bool occluded;
    }

    /// <summary>Ambient Life 每帧输出（全是数值语义，不含任何 Unity 类型）。</summary>
    public struct AmbientFrame
    {
        public float breathChestPitchDeg;
        public float breathChestLiftDeg;
        public float breathBellyPitchDeg;
        public float breathHeadBobDeg;
        public int breathPhase;

        public int postureState;
        public float hipsSideMeters;
        public float hipsRollDeg;
        public float chestRollDeg;
        public float chestYawDeg;
        public float chestPitchDeg;

        public float headYawDeg;
        public float headPitchDeg;
        public float headRollDeg;
        public float gazeYawDeg;
        public float gazePitchDeg;
        public int gazeTarget;
        public float blinkWeight;

        public float microHeadYawDeg;
        public float microHeadPitchDeg;
        public float microHeadRollDeg;
        public float microShoulderDeg;
        public float microArmDeg;
        public float microBodyDeg;
        public string ambientAction;

        public float activity;
        public float attention;
        public float energy;
        public float relaxation;
        public bool explicitBehaviorActive;
        public bool recoveryActive;
    }

    /// <summary>确定性随机数（xorshift），保证测试可复现。</summary>
    internal sealed class DeterministicRandom
    {
        private uint _state;

        public DeterministicRandom(int seed)
        {
            _state = seed == 0 ? 2463534242u : (uint)seed;
        }

        public float Next01()
        {
            _state ^= _state << 13;
            _state ^= _state >> 17;
            _state ^= _state << 5;
            return (_state & 0xFFFFFF) / (float)0x1000000;
        }

        public float Range(float min, float max)
        {
            return min + (max - min) * Next01();
        }

        public int RangeInt(int minInclusive, int maxExclusive)
        {
            if (maxExclusive <= minInclusive)
            {
                return minInclusive;
            }
            return minInclusive + (int)(Next01() * (maxExclusive - minInclusive));
        }
    }

    /// <summary>
    /// Ambient Life 主逻辑。调用方以 10~30Hz 调 Tick（插值放在 MonoBehaviour 侧），
    /// 事件通过 Notify* 注入。
    /// </summary>
    public sealed class AmbientLifeCore
    {
        private sealed class MicroAction
        {
            public string name;
            public float minCooldown;
            public float maxCooldown;
            public float minAmp;
            public float maxAmp;
            public float minDuration;
            public float maxDuration;
            public float nextAllowedAt;
        }

        private sealed class IdleAction
        {
            public string name;
            public float threshold;
            public float minCooldown;
            public float maxCooldown;
            public float duration;
            public float nextAllowedAt;
            public float minIdleSeconds;
        }

        private readonly PersonalityMotionProfile _profile;
        private readonly DeterministicRandom _random;
        private readonly List<MicroAction> _microActions = new List<MicroAction>();
        private readonly List<IdleAction> _idleActions = new List<IdleAction>();

        private float _time;

        private float _activity;
        private float _activityTarget;
        private float _attention;
        private float _attentionTarget;
        private float _energy;
        private float _relaxation;

        private float _breathPhaseTime;
        private float _breathCycleLength;
        private int _breathPhase;
        private float _breathAmplitude = 1f;

        private float _nextBlinkAt;
        private float _blinkStartedAt = -1f;
        private float _blinkDuration = 0.13f;
        private int _blinkPending;
        private float _lastBlinkAt = -99f;
        private float _lastGazeShiftAt = -99f;
        private float _blinkWeight;

        private float _gazeYaw;
        private float _gazePitch;
        private float _gazeYawTarget;
        private float _gazePitchTarget;
        private float _nextGazeShiftAt;
        private int _gazeTarget;
        private float _explicitGazeUntil;

        private int _postureState;
        private float _nextPostureChangeAt;
        private float _postureHold;
        private float _hipsSide;
        private float _hipsRoll;

        private float _nextMicroAllowedAt;
        private float _nextIdleAllowedAt;
        private MicroAction _activeMicro;
        private float _microStartedAt;
        private float _microDuration;
        private float _microAmplitude;
        private float _microSign;

        private IdleAction _activeIdle;
        private float _idleActionStartedAt;
        private float _idleActionDuration;

        private float _explicitUntil;
        private string _explicitName = "";
        private float _recoveryUntil;
        private string _recoveryFrom = "";

        public AmbientLifeCore(PersonalityMotionProfile profile = null, int seed = 20260912)
        {
            _profile = profile ?? PersonalityMotionProfile.Balanced();
            _random = new DeterministicRandom(seed);
            _activity = 0.35f;
            _attention = 0.5f;
            _energy = _profile.energy;
            _relaxation = 0.4f;
            _breathCycleLength = NextBreathCycle();
            _nextBlinkAt = _random.Range(1.2f, 3.5f);
            _nextGazeShiftAt = _random.Range(2.5f, 6f);
            _gazeTarget = 1;      // 有用户时默认先看用户，而不是先看环境
            _nextPostureChangeAt = _random.Range(18f, 40f);
            BuildMicroActions();
            BuildIdleActions();
        }

        public PersonalityMotionProfile Profile => _profile;
        public float Activity => _activity;
        public float Attention => _attention;
        public float Energy => _energy;
        public float Relaxation => _relaxation;
        public string ActiveAmbientAction =>
            _activeIdle != null ? _activeIdle.name
            : (_activeMicro != null ? _activeMicro.name : "");
        public bool ExplicitBehaviorActive => _time < _explicitUntil;
        public bool RecoveryActive => _time < _recoveryUntil;
        public int BreathPhase => _breathPhase;
        public float BlinkWeight => _blinkWeight;
        public int GazeTarget => _gazeTarget;
        public int PostureState => _postureState;
        public float Time => _time;

        /// <summary>显式行为开始：Ambient 让位（第十四/二十节）。</summary>
        public void NotifyExplicitBehavior(string name, float priority = 80f,
                                           float expectedDuration = 2f)
        {
            _explicitName = name ?? "";
            _explicitUntil = _time + Math.Max(0.2f, expectedDuration);
            _recoveryUntil = 0f;
            if (priority >= 50f)
            {
                _activeMicro = null;
                _activeIdle = null;
            }
            if (IsSocialAction(_explicitName))
            {
                _explicitGazeUntil = _explicitUntil + 0.4f;
            }
        }

        /// <summary>显式行为结束：进入恢复阶段，而不是瞬间归零。</summary>
        public void NotifyBehaviorComplete(string name = "")
        {
            _explicitUntil = Math.Min(_explicitUntil, _time);
            _recoveryFrom = string.IsNullOrEmpty(name) ? _explicitName : name;
            _recoveryUntil = _time + _random.Range(0.9f, 1.8f);
        }

        /// <summary>外部（行为/注意力系统）要求注视某处。</summary>
        public void NotifyGazeOverride(bool atUser, float holdSeconds = 1.5f)
        {
            _explicitGazeUntil = _time + Math.Max(0.2f, holdSeconds);
            if (atUser)
            {
                _gazeTarget = 1;
                _gazeYawTarget = 0f;
                _gazePitchTarget = 0f;
            }
        }

        // ------------------------------------------------------------------ 主循环
        public AmbientFrame Tick(float dt, AmbientContext ctx)
        {
            if (dt <= 0f)
            {
                dt = 0.033f;
            }
            _time += dt;
            UpdateRhythm(dt, ctx);
            UpdateBreathing(dt);
            UpdateBlink();
            UpdateGaze(dt, ctx);
            UpdatePosture(dt, ctx);
            UpdateMicroMotion(dt, ctx);
            UpdateIdleActions(ctx);

            var frame = new AmbientFrame();
            var phaseLen = PhaseLength(_breathPhase);
            var progress = phaseLen <= 0f ? 0f : Clamp01(_breathPhaseTime / phaseLen);
            float breathCurve;
            switch (_breathPhase)
            {
                case 0: breathCurve = Mathf_SmoothStep(progress); break;      // inhale
                case 1: breathCurve = 1f; break;                              // hold
                case 2: breathCurve = 1f - Mathf_SmoothStep(progress); break;  // exhale
                default: breathCurve = 0.06f; break;                          // relax
            }
            var breathAmp = _breathAmplitude * (0.55f + 0.65f * _activity);
            frame.breathPhase = _breathPhase;
            frame.breathChestPitchDeg = -1.15f * breathAmp * breathCurve;
            frame.breathChestLiftDeg = 0.45f * breathAmp * breathCurve;
            frame.breathBellyPitchDeg = 0.35f * breathAmp * breathCurve;
            frame.breathHeadBobDeg = 0.22f * breathAmp * breathCurve;

            frame.postureState = _postureState;
            frame.hipsSideMeters = _hipsSide;
            frame.hipsRollDeg = _hipsRoll;
            frame.chestRollDeg = -_hipsRoll * 0.45f;

            frame.headYawDeg = _gazeYaw * 0.35f;
            frame.headPitchDeg = _gazePitch * 0.30f;
            frame.gazeYawDeg = _gazeYaw * 0.65f;
            frame.gazePitchDeg = _gazePitch * 0.70f;
            frame.gazeTarget = _gazeTarget;
            frame.blinkWeight = _blinkWeight;

            var micro = MicroOffsets();
            frame.microHeadYawDeg = micro[0];
            frame.microHeadPitchDeg = micro[1];
            frame.microHeadRollDeg = micro[2];
            frame.microShoulderDeg = micro[3];
            frame.microArmDeg = micro[4];
            frame.microBodyDeg = micro[5];
            frame.ambientAction = ActiveAmbientAction;

            frame.activity = _activity;
            frame.attention = _attention;
            frame.energy = _energy;
            frame.relaxation = _relaxation;
            frame.explicitBehaviorActive = ExplicitBehaviorActive;
            frame.recoveryActive = RecoveryActive;
            return frame;
        }

        // ------------------------------------------------------------------ 生命节奏
        private void UpdateRhythm(float dt, AmbientContext ctx)
        {
            _attentionTarget = 0.25f * _profile.socialAttention;
            if (ctx.userPresent) { _attentionTarget += 0.25f; }
            if (ctx.userSpeaking) { _attentionTarget += 0.30f; }
            if (ctx.userLookingAtAvatar) { _attentionTarget += 0.25f; }
            if (ctx.userApproaching) { _attentionTarget += 0.20f; }
            if (ctx.userPresent && ctx.userDistance < 1.5f) { _attentionTarget += 0.10f; }
            if (ctx.conversationActive) { _attentionTarget += 0.20f; }
            _attentionTarget = Clamp01(_attentionTarget);

            var idle = Math.Max(0f, ctx.userIdleSeconds);
            _activityTarget = 0.35f;
            if (ctx.conversationActive) { _activityTarget += 0.45f; }
            if (ctx.userSpeaking) { _activityTarget += 0.15f; }
            if (ctx.explicitBehaviorActive) { _activityTarget += 0.25f; }
            if (ctx.locomotionActive) { _activityTarget += 0.20f; }
            // 沉默 30s 开始下降，5 分钟进入放松待机
            var decay = Math.Min(0.45f, idle / 120f);
            _activityTarget = Clamp01(_activityTarget - decay);

            _activity = Damp(_activity, _activityTarget, 0.6f, dt);
            _attention = Damp(_attention, _attentionTarget,
                              ctx.userSpeaking ? 2.5f : 0.8f, dt);
            _relaxation = Damp(_relaxation,
                               Clamp01(1f - _activity + 0.25f * (1f - _attention)),
                               0.25f, dt);
            _energy = Damp(_energy,
                           Clamp01(_profile.energy * (0.7f + 0.5f * _activity)),
                           0.2f, dt);
        }

        // ------------------------------------------------------------------ 呼吸
        private float NextBreathCycle()
        {
            return _random.Range(2.8f, 4.8f) / Math.Max(0.3f, 0.7f + 0.5f * _activity);
        }

        private float PhaseLength(int phase)
        {
            switch (phase)
            {
                case 0: return _breathCycleLength * 0.38f;
                case 1: return _breathCycleLength * 0.10f;
                case 2: return _breathCycleLength * 0.44f;
                default: return _breathCycleLength * 0.08f;
            }
        }

        private void UpdateBreathing(float dt)
        {
            _breathPhaseTime += dt;
            if (_breathPhaseTime >= PhaseLength(_breathPhase))
            {
                _breathPhaseTime = 0f;
                _breathPhase = (_breathPhase + 1) % 4;
                if (_breathPhase == 0)
                {
                    _breathCycleLength = NextBreathCycle();
                    _breathAmplitude = _random.Range(0.85f, 1.18f);
                }
            }
        }

        // ------------------------------------------------------------------ 眨眼
        private void UpdateBlink()
        {
            if (_blinkStartedAt >= 0f)
            {
                var progress = (_time - _blinkStartedAt) / Math.Max(0.05f, _blinkDuration);
                if (progress >= 1f)
                {
                    _blinkStartedAt = -1f;
                    _blinkWeight = 0f;
                    _lastBlinkAt = _time;
                    if (_blinkPending > 0)
                    {
                        _blinkPending--;
                        _blinkStartedAt = _time + _random.Range(0.06f, 0.14f);
                        _blinkDuration = _random.Range(0.09f, 0.13f);
                        _blinkWeight = 0f;
                    }
                    else
                    {
                        ScheduleNextBlink();
                    }
                }
                else
                {
                    _blinkWeight = progress < 0.5f ? progress * 2f
                                                   : (1f - progress) * 2f;
                }
                return;
            }
            if (_time < _nextBlinkAt)
            {
                return;
            }
            // 类型：普通最多，双眨/慢眨概率很低（第七节）
            var roll = _random.Next01();
            _blinkPending = 0;
            _blinkDuration = _random.Range(0.11f, 0.15f);
            if (roll < 0.03f)
            {
                _blinkDuration = _random.Range(0.45f, 0.80f);   // 慢眨
            }
            else if (roll < 0.11f)
            {
                _blinkPending = 1;                               // 双眨
            }
            if (_time - _lastBlinkAt > 9f)
            {
                _nextBlinkAt = _time;                            // 久未眨眼加速补偿
            }
            _blinkStartedAt = _time;
        }

        private void ScheduleNextBlink()
        {
            var baseInterval = _random.Range(2.5f, 6.5f);
            var factor = Math.Max(0.4f,
                _profile.blinkRate * (0.85f + 0.30f * _activity));
            var interval = baseInterval / factor;
            if (_time - _lastGazeShiftAt < 0.5f && _random.Next01() < 0.25f)
            {
                interval = Math.Min(interval, _random.Range(0.25f, 0.70f));
            }
            _nextBlinkAt = _time + interval;
        }

        // ------------------------------------------------------------------ 视线
        private void UpdateGaze(float dt, AmbientContext ctx)
        {
            if (_time < _explicitGazeUntil)
            {
                _gazeTarget = 1;
                _gazeYaw = Damp(_gazeYaw, 0f, 6f, dt);
                _gazePitch = Damp(_gazePitch, 0f, 6f, dt);
                return;
            }
            // 注意力很高时，环境注视最多停留 1.2s 就必须回到用户（第九/十节）
            if (_attention >= 0.75f && ctx.userPresent && _gazeTarget != 1 &&
                _time - _lastGazeShiftAt > 1.2f)
            {
                _gazeTarget = 1;
                _gazeYawTarget = _random.Range(-2.5f, 2.5f);
                _gazePitchTarget = _random.Range(-1.5f, 1.5f);
                _lastGazeShiftAt = _time;
                _nextGazeShiftAt = _time + _random.Range(1.6f, 4.0f);
            }
            if (_time >= _nextGazeShiftAt)
            {
                var hold = _random.Range(1.6f, 4.5f)
                           / Math.Max(0.4f, _profile.gazeFrequency);
                if (_attention >= 0.55f && ctx.userPresent)
                {
                    // 注意力越高越少移开；移开也只是"短暂一瞥"
                    var awayProbability = 0.35f * (1f - _attention);
                    if (_gazeTarget == 1 && _random.Next01() < awayProbability)
                    {
                        PickAmbientGazeTarget(ctx);
                        hold = _random.Range(0.5f, 1.4f);
                    }
                    else
                    {
                        _gazeTarget = 1;
                        _gazeYawTarget = _random.Range(-2.5f, 2.5f);
                        _gazePitchTarget = _random.Range(-1.5f, 1.5f);
                    }
                }
                else
                {
                    PickAmbientGazeTarget(ctx);
                }
                _lastGazeShiftAt = _time;
                _nextGazeShiftAt = _time + hold * (0.7f + 0.6f * _activity);
            }
            var speed = _gazeTarget == 1 ? 5.5f : 3.2f;
            _gazeYaw = Damp(_gazeYaw, _gazeYawTarget, speed, dt);
            _gazePitch = Damp(_gazePitch, _gazePitchTarget, speed, dt);
        }

        private void PickAmbientGazeTarget(AmbientContext ctx)
        {
            _gazeTarget = 2;
            if (Math.Abs(_gazeYaw) < 6f)
            {
                _gazeYawTarget = _random.Next01() < 0.5f
                    ? _random.Range(-16f, -7f)
                    : _random.Range(7f, 16f);
            }
            else
            {
                _gazeYawTarget = _gazeYaw > 0
                    ? _random.Range(-14f, -4f)
                    : _random.Range(4f, 14f);
            }
            _gazePitchTarget = _random.Next01() < 0.3f
                ? _random.Range(4f, 10f)
                : _random.Range(-8f, 2f);
            if (!ctx.userPresent && _random.Next01() < 0.25f)
            {
                _gazePitchTarget = _random.Range(-18f, -8f);
            }
        }

        // ------------------------------------------------------------------ 姿态
        private void UpdatePosture(float dt, AmbientContext ctx)
        {
            if (_postureHold > 0f)
            {
                _postureHold -= dt;
            }
            if (_time < _nextPostureChangeAt || _postureHold > 0f)
            {
                return;
            }
            if (ExplicitBehaviorActive && ctx.explicitBehaviorPriority >= 70f)
            {
                _nextPostureChangeAt = _time + _random.Range(3f, 7f);
                return;
            }
            var roll = _random.Next01();
            _postureState = roll < 0.36f ? 1 : (roll < 0.72f ? 2 : 0);
            var scale = _profile.postureVariability * (0.7f + 0.5f * (1f - _activity));
            _hipsSide = _postureState == 1 ? -0.012f * scale
                       : _postureState == 2 ? 0.012f * scale : 0f;
            _hipsRoll = _postureState == 1 ? 1.1f * scale
                        : _postureState == 2 ? -1.1f * scale : 0f;
            _postureHold = _random.Range(1.2f, 2.6f);
            var interval = _random.Range(17f, 51f)
                           / Math.Max(0.4f, _profile.postureVariability);
            _nextPostureChangeAt = _time + interval * (1.2f - 0.4f * _activity);
        }

        // ------------------------------------------------------------------ 微动作
        private void BuildMicroActions()
        {
            _microActions.Clear();
            _microActions.Add(new MicroAction { name = "micro_head_tilt", minCooldown = 7f, maxCooldown = 16f, minAmp = 2f, maxAmp = 5f, minDuration = 0.5f, maxDuration = 1.4f });
            _microActions.Add(new MicroAction { name = "micro_head_adjust", minCooldown = 9f, maxCooldown = 22f, minAmp = 1.5f, maxAmp = 3.5f, minDuration = 0.4f, maxDuration = 1.0f });
            _microActions.Add(new MicroAction { name = "micro_shoulder_shift", minCooldown = 12f, maxCooldown = 28f, minAmp = 1.2f, maxAmp = 3f, minDuration = 0.6f, maxDuration = 1.5f });
            _microActions.Add(new MicroAction { name = "micro_arm_adjust", minCooldown = 15f, maxCooldown = 34f, minAmp = 1.5f, maxAmp = 4f, minDuration = 0.5f, maxDuration = 1.3f });
            _microActions.Add(new MicroAction { name = "micro_body_shift", minCooldown = 14f, maxCooldown = 30f, minAmp = 0.8f, maxAmp = 2.2f, minDuration = 0.7f, maxDuration = 1.6f });
            _microActions.Add(new MicroAction { name = "micro_fidget", minCooldown = 20f, maxCooldown = 46f, minAmp = 1.5f, maxAmp = 4f, minDuration = 0.6f, maxDuration = 1.5f });
        }

        private void UpdateMicroMotion(float dt, AmbientContext ctx)
        {
            if (_activeMicro != null)
            {
                if (_time - _microStartedAt >= _microDuration)
                {
                    _activeMicro = null;
                }
                return;
            }
            if (ExplicitBehaviorActive || ctx.explicitBehaviorPriority >= 50f)
            {
                return;
            }
            if (ctx.locomotionActive && ctx.locomotionSpeed > 0.15f)
            {
                return;
            }
            // 全局微动作冷却：人不会每两秒就动一下（提示词第六/十七节）
            if (_time < _nextMicroAllowedAt)
            {
                return;
            }
            var rate = _profile.movementFrequency * (0.5f + _activity);
            if (_random.Next01() >= dt * 0.25f * rate)
            {
                return;
            }
            var candidates = new List<MicroAction>();
            foreach (var action in _microActions)
            {
                if (_time >= action.nextAllowedAt)
                {
                    candidates.Add(action);
                }
            }
            if (candidates.Count == 0)
            {
                return;
            }
            var pick = candidates[_random.RangeInt(0, candidates.Count)];
            _activeMicro = pick;
            pick.nextAllowedAt = _time
                + _random.Range(pick.minCooldown, pick.maxCooldown) / Math.Max(0.4f, rate);
            _microStartedAt = _time;
            _microDuration = _random.Range(pick.minDuration, pick.maxDuration);
            _microAmplitude = _random.Range(pick.minAmp, pick.maxAmp);
            _microSign = _random.Next01() < 0.5f ? -1f : 1f;
            _nextMicroAllowedAt = _time + _random.Range(4.5f, 10f) / Math.Max(0.4f, rate);
        }

        /// <summary>微动作输出：头 yaw/pitch/roll、肩、手臂、身体。</summary>
        private float[] MicroOffsets()
        {
            var result = new float[6];
            if (_activeMicro == null)
            {
                return result;
            }
            var t = (_time - _microStartedAt) / Math.Max(0.05f, _microDuration);
            if (t < 0f || t > 1f)
            {
                return result;
            }
            var curve = Mathf_SmoothStep(t) * (1f - t) + t * (1f - t) * 0.8f;
            var amp = _microAmplitude * curve * _microSign;
            switch (_activeMicro.name)
            {
                case "micro_head_tilt":
                    result[2] = amp;
                    result[0] = amp * 0.4f;
                    break;
                case "micro_head_adjust":
                    result[1] = amp;
                    break;
                case "micro_shoulder_shift":
                    result[3] = amp;
                    break;
                case "micro_arm_adjust":
                    result[4] = amp;
                    break;
                case "micro_body_shift":
                    result[5] = amp;
                    break;
                case "micro_fidget":
                    result[4] = amp;
                    result[3] = amp * 0.5f;
                    break;
            }
            return result;
        }

        // ------------------------------------------------------------------ idle 动作
        private void BuildIdleActions()
        {
            _idleActions.Clear();
            _idleActions.Add(new IdleAction { name = "look_around", threshold = 0.58f, minCooldown = 95f, maxCooldown = 230f, duration = 2.4f, minIdleSeconds = 45f });
            _idleActions.Add(new IdleAction { name = "weight_shift", threshold = 0.66f, minCooldown = 130f, maxCooldown = 280f, duration = 2.0f, minIdleSeconds = 70f });
            _idleActions.Add(new IdleAction { name = "stretch", threshold = 0.86f, minCooldown = 260f, maxCooldown = 520f, duration = 3.2f, minIdleSeconds = 140f });
            _idleActions.Add(new IdleAction { name = "yawn", threshold = 0.93f, minCooldown = 320f, maxCooldown = 640f, duration = 2.6f, minIdleSeconds = 200f });
        }

        private void UpdateIdleActions(AmbientContext ctx)
        {
            if (_activeIdle != null)
            {
                if (_time - _idleActionStartedAt >= _idleActionDuration)
                {
                    _activeIdle = null;
                }
                return;
            }
            if (ExplicitBehaviorActive || ctx.conversationActive || ctx.userSpeaking)
            {
                return;
            }
            if (ctx.locomotionActive && ctx.locomotionSpeed > 0.15f)
            {
                return;
            }
            // 全局 idle 冷却：即使多个动作都够资格，也不要连着来
            if (_time < _nextIdleAllowedAt)
            {
                return;
            }
            foreach (var action in _idleActions)
            {
                if (_time < action.nextAllowedAt)
                {
                    continue;
                }
                var idleFactor = Clamp01(
                    (ctx.userIdleSeconds - action.minIdleSeconds) / 240f);
                var utility = idleFactor
                              * _profile.fidgetFrequency
                              * (0.5f + 0.9f * _relaxation)
                              * (1.15f - _activity)
                              * _random.Range(0.7f, 1.35f);
                if (utility >= action.threshold)
                {
                    _activeIdle = action;
                    _idleActionStartedAt = _time;
                    _idleActionDuration = action.duration;
                    action.nextAllowedAt = _time
                        + _random.Range(action.minCooldown, action.maxCooldown)
                          / Math.Max(0.4f, _profile.fidgetFrequency);
                    _nextIdleAllowedAt = _time + _random.Range(70f, 180f)
                                          / Math.Max(0.4f, _profile.fidgetFrequency);
                    return;
                }
            }
        }

        // ------------------------------------------------------------------ 工具
        public static float Clamp01(float value)
        {
            return value < 0f ? 0f : (value > 1f ? 1f : value);
        }

        /// <summary>指数趋近（critically damped 近似），保证平滑加速/减速。</summary>
        public static float Damp(float current, float target, float speed, float dt)
        {
            var factor = 1f - (float)Math.Exp(-Math.Max(0.001f, speed) * dt);
            return current + (target - current) * factor;
        }

        public static float Mathf_SmoothStep(float t)
        {
            t = Clamp01(t);
            return t * t * (3f - 2f * t);
        }

        private static bool IsSocialAction(string name)
        {
            if (string.IsNullOrEmpty(name))
            {
                return false;
            }
            switch (name)
            {
                case "wave":
                case "point":
                case "nod":
                case "shake_head":
                case "high_five":
                case "handshake":
                case "offer_hand":
                case "greeting":
                case "look_at_user":
                case "speak":
                case "listen_user":
                    return true;
                default:
                    return false;
            }
        }

        /// <summary>调试单行状态（Release 不要每帧打）。</summary>
        public string DebugLine()
        {
            var sb = new StringBuilder();
            sb.Append("[AmbientLife] activity=").Append(_activity.ToString("F2", CultureInfo.InvariantCulture));
            sb.Append(" attention=").Append(_attention.ToString("F2", CultureInfo.InvariantCulture));
            sb.Append(" energy=").Append(_energy.ToString("F2", CultureInfo.InvariantCulture));
            sb.Append(" gazeTarget=").Append(_gazeTarget);
            sb.Append(" yaw=").Append(_gazeYaw.ToString("F1", CultureInfo.InvariantCulture));
            sb.Append(" pitch=").Append(_gazePitch.ToString("F1", CultureInfo.InvariantCulture));
            sb.Append(" posture=").Append(_postureState);
            sb.Append(" breath=").Append(_breathPhase);
            sb.Append(" blink=").Append(_blinkWeight.ToString("F2", CultureInfo.InvariantCulture));
            sb.Append(" ambient=").Append(ActiveAmbientAction);
            if (ExplicitBehaviorActive)
            {
                sb.Append(" suppressedBy=").Append(_explicitName);
            }
            if (RecoveryActive)
            {
                sb.Append(" recoveringFrom=").Append(_recoveryFrom);
            }
            return sb.ToString();
        }
    }
}



