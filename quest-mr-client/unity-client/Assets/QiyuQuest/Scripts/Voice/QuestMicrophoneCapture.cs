using System;
using System.Collections.Generic;
using Qiyu.Quest.Networking;
using UnityEngine;
#if UNITY_ANDROID && !UNITY_EDITOR
using UnityEngine.Android;
#endif

namespace Qiyu.Quest.Voice
{
    /// <summary>
    /// Quest 麦克风采集 + 能量 VAD。
    ///
    /// 复用 Unity Microphone API（不自造音频后端）：
    /// - 采集 48kHz 单声道，降采样为 16kHz PCM16；
    /// - 本地 VAD 判断说话开始/结束，避免把静音整段上传；
    /// - 说话期间通过 Protocol v1 二进制帧上传，结束时发 user.audio_end；
    /// - TTS 播放中检测到用户说话 → 触发 barge-in。
    /// </summary>
    public class QuestMicrophoneCapture : MonoBehaviour
    {
        [Header("依赖")]
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;

        [Header("采集")]
        [SerializeField] private bool autoStart = true;
        [SerializeField] private int captureSampleRate = 48000;
        [SerializeField] private int targetSampleRate = 16000;
        [SerializeField] private bool mute = false;

        [Header("VAD")]
        [Tooltip("RMS 能量阈值；安静室内建议 0.015~0.03")]
        [SerializeField] private float vadThreshold = 0.02f;
        [SerializeField] private int minSpeechMs = 200;
        [SerializeField] private int silenceMs = 700;
        [SerializeField] private int maxUtteranceMs = 15000;
        [SerializeField] private int preRollMs = 300;
        [Tooltip("TTS 播放中判定用户插话的更高能量阈值")]
        [SerializeField] private float bargeInRmsThreshold = 0.06f;

        private AudioClip _clip;
        private string _device = "";
        private int _clipSamples;
        private int _lastPosition;
        private float[] _readBuffer;
        private readonly List<short> _pending = new List<short>();
        private readonly Queue<short[]> _preRoll = new Queue<short[]>();
        private int _preRollFrames;
        private int _frameSize;
        private int _frameMs;
        private int _voicedMs;
        private int _silenceMs;
        private int _speechMs;
        private uint _sequence;
        private bool _bargeInFired;

        public bool IsCapturing { get; private set; }
        public bool IsSpeaking { get; private set; }
        public float LastRms { get; private set; }
        /// <summary>由 QuestVoiceLoop 注入：TTS 是否正在播放。</summary>
        public Func<bool> IsTtsPlaying { get; set; }

        public event Action OnSpeechStart;
        public event Action OnSpeechEnd;
        public event Action OnBargeInDetected;

        private void Start()
        {
            if (autoStart)
            {
                StartCapture();
            }
        }

        public void StartCapture()
        {
            if (IsCapturing)
            {
                return;
            }
            if (!EnsureMicrophonePermission())
            {
                return;
            }
            if (Microphone.devices == null || Microphone.devices.Length == 0)
            {
                Debug.LogError("[QuestMic] 未找到麦克风设备");
                return;
            }
            _device = Microphone.devices[0];
            _clip = Microphone.Start(_device, true, 1, captureSampleRate);
            if (_clip == null && captureSampleRate != targetSampleRate)
            {
                Debug.LogWarning($"[QuestMic] {captureSampleRate}Hz 不受支持，回退到 {targetSampleRate}Hz");
                captureSampleRate = targetSampleRate;
                _clip = Microphone.Start(_device, true, 1, captureSampleRate);
            }
            if (_clip == null)
            {
                Debug.LogError("[QuestMic] Microphone.Start 失败");
                return;
            }
            _clipSamples = _clip.samples;
            _lastPosition = 0;
            _frameSize = Mathf.Max(80, targetSampleRate / 50); // 20ms
            _frameMs = Mathf.RoundToInt(1000f * _frameSize / targetSampleRate);
            _preRollFrames = Mathf.Max(1, preRollMs / Mathf.Max(1, _frameMs));
            _pending.Clear();
            _preRoll.Clear();
            IsCapturing = true;
            Debug.Log($"[QuestMic] 开始采集 device={_device} rate={captureSampleRate}");
        }

        public void StopCapture()
        {
            if (!IsCapturing)
            {
                return;
            }
            if (IsSpeaking)
            {
                EndSpeech();
            }
            if (Microphone.IsRecording(_device))
            {
                Microphone.End(_device);
            }
            IsCapturing = false;
            _clip = null;
        }

        public void SetMuted(bool value)
        {
            mute = value;
        }

        private void Update()
        {
            if (!IsCapturing || mute || _clip == null)
            {
                return;
            }
            ReadAvailableSamples();
        }

        private void ReadAvailableSamples()
        {
            var position = Microphone.GetPosition(_device);
            if (position < 0)
            {
                return;
            }
            var available = position - _lastPosition;
            if (available < 0)
            {
                available += _clipSamples;
            }
            if (available <= 0)
            {
                return;
            }
            if (_readBuffer == null || _readBuffer.Length < available)
            {
                _readBuffer = new float[available];
            }
            if (_lastPosition + available <= _clipSamples)
            {
                _clip.GetData(_readBuffer, _lastPosition);
            }
            else
            {
                var headLength = _clipSamples - _lastPosition;
                var head = new float[headLength];
                _clip.GetData(head, _lastPosition);
                Array.Copy(head, 0, _readBuffer, 0, headLength);
                var tailLength = available - headLength;
                var tail = new float[tailLength];
                _clip.GetData(tail, 0);
                Array.Copy(tail, 0, _readBuffer, headLength, tailLength);
            }
            _lastPosition = position;
            DownsampleAndProcess(_readBuffer, available);
        }

        private void DownsampleAndProcess(float[] source, int count)
        {
            if (captureSampleRate == targetSampleRate)
            {
                for (var i = 0; i < count; i++)
                {
                    _pending.Add(FloatToPcm16(source[i]));
                }
            }
            else
            {
                var ratio = captureSampleRate / (float)targetSampleRate;
                var outCount = Mathf.FloorToInt(count / ratio);
                for (var i = 0; i < outCount; i++)
                {
                    var start = Mathf.FloorToInt(i * ratio);
                    var end = Mathf.Min(count, Mathf.FloorToInt((i + 1) * ratio));
                    var sum = 0f;
                    var n = 0;
                    for (var j = start; j < end; j++)
                    {
                        sum += source[j];
                        n++;
                    }
                    _pending.Add(FloatToPcm16(n > 0 ? sum / n : source[start]));
                }
            }
            ProcessFrames();
        }

        private void ProcessFrames()
        {
            while (_pending.Count >= _frameSize)
            {
                var frame = new short[_frameSize];
                _pending.CopyTo(0, frame, 0, _frameSize);
                _pending.RemoveRange(0, _frameSize);
                ProcessFrame(frame);
            }
        }

        private void ProcessFrame(short[] frame)
        {
            var rms = ComputeRms(frame);
            LastRms = rms;
            var voiced = rms >= vadThreshold;
            var ttsPlaying = IsTtsPlaying != null && IsTtsPlaying();

            if (!IsSpeaking)
            {
                PushPreRoll(frame);
                if (ttsPlaying && rms >= bargeInRmsThreshold)
                {
                    _voicedMs += _frameMs;
                    if (!_bargeInFired && _voicedMs >= minSpeechMs)
                    {
                        _bargeInFired = true;
                        OnBargeInDetected?.Invoke();
                    }
                }
                else if (voiced)
                {
                    _voicedMs += _frameMs;
                    if (_voicedMs >= minSpeechMs)
                    {
                        StartSpeech();
                    }
                }
                else
                {
                    _voicedMs = 0;
                    _bargeInFired = false;
                }
                return;
            }

            SendFrame(frame);
            _speechMs += _frameMs;
            if (voiced)
            {
                _silenceMs = 0;
            }
            else
            {
                _silenceMs += _frameMs;
            }
            if (_silenceMs >= silenceMs || _speechMs >= maxUtteranceMs)
            {
                EndSpeech();
            }
        }

        private void StartSpeech()
        {
            IsSpeaking = true;
            _speechMs = 0;
            _silenceMs = 0;
            _voicedMs = 0;
            while (_preRoll.Count > 0)
            {
                SendFrame(_preRoll.Dequeue());
            }
            OnSpeechStart?.Invoke();
            Debug.Log("[QuestMic] 检测到说话开始");
        }

        private void EndSpeech()
        {
            IsSpeaking = false;
            _silenceMs = 0;
            _speechMs = 0;
            _voicedMs = 0;
            _bargeInFired = false;
            _preRoll.Clear();
            if (webSocketClient != null && webSocketClient.HandshakeDone)
            {
                var payload = new Newtonsoft.Json.Linq.JObject
                {
                    ["sample_rate"] = targetSampleRate,
                    ["channels"] = 1
                };
                _ = webSocketClient.SendAsync(new QuestEnvelope(
                    "user.audio_end", payload, webSocketClient.SessionId));
            }
            OnSpeechEnd?.Invoke();
            Debug.Log("[QuestMic] 说话结束，已请求 STT");
        }

        private void PushPreRoll(short[] frame)
        {
            _preRoll.Enqueue(frame);
            while (_preRoll.Count > _preRollFrames)
            {
                _preRoll.Dequeue();
            }
        }

        private void SendFrame(short[] frame)
        {
            if (webSocketClient == null || !webSocketClient.HandshakeDone)
            {
                return;
            }
            var bytes = new byte[frame.Length * 2];
            for (var i = 0; i < frame.Length; i++)
            {
                bytes[i * 2] = (byte)(frame[i] & 0xFF);
                bytes[i * 2 + 1] = (byte)((frame[i] >> 8) & 0xFF);
            }
            var packed = QuestBinaryProtocol.Pack(
                QuestBinaryProtocol.KindAudioInPcm16, _sequence++, bytes);
            _ = webSocketClient.SendBinaryAsync(packed);
        }

        private static float ComputeRms(short[] frame)
        {
            if (frame.Length == 0)
            {
                return 0f;
            }
            double sum = 0;
            for (var i = 0; i < frame.Length; i++)
            {
                var v = frame[i] / 32768.0;
                sum += v * v;
            }
            return Mathf.Sqrt((float)(sum / frame.Length));
        }

        private static short FloatToPcm16(float value)
        {
            var v = Mathf.Clamp(value, -1f, 1f);
            return (short)Mathf.RoundToInt(v * 32767f);
        }

        private bool EnsureMicrophonePermission()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (!Permission.HasUserAuthorizedPermission(Permission.Microphone))
            {
                Permission.RequestUserPermission(Permission.Microphone);
                Debug.LogWarning("[QuestMic] 正在请求麦克风权限，授权后请重新 StartCapture");
                return false;
            }
#endif
            return true;
        }

        private void OnDestroy()
        {
            StopCapture();
        }
    }
}
