using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Qiyu.Quest.Networking;
using UnityEngine;

namespace Qiyu.Quest.Voice
{
    /// <summary>
    /// 接收 Gateway 的 TTS PCM16 二进制流并实时播放。
    ///
    /// - 音频由 Qiyu 后端 TTS 合成（不是客户端假发声）；
    /// - 按 audio.tts_start 的总字节数预建 AudioClip，边收边 SetData；
    /// - 预缓冲后开始播放，降低首包延迟；
    /// - 打断时立即停止；
    /// - 播放期间从输出采样计算 RMS 驱动口型（真实音频驱动，非随机动画）。
    /// </summary>
    [RequireComponent(typeof(AudioSource))]
    public class QuestTtsPlayer : MonoBehaviour
    {
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private float prebufferSeconds = 0.18f;
        [SerializeField] private float volume = 1f;

        private AudioSource _source;
        private AudioClip _clip;
        private float[] _clipBuffer;
        private int _totalSamples;
        private int _writtenSamples;
        private int _receivedBytes;
        private int _expectedBytes;
        private int _sampleRate = 16000;
        private bool _playing;
        private bool _finalChunkReceived;
        private float[] _outputBuffer;

        public bool IsPlaying => _playing;
        /// <summary>当前播放响度（0~1），供口型/表情驱动。</summary>
        public float MouthAmplitude { get; private set; }
        public string CurrentText { get; private set; } = "";
        public string ResponseId { get; private set; } = "";

        public event Action<string> OnSpeechSegmentStart;
        public event Action<string, bool> OnSpeechSegmentEnd;

        private void Awake()
        {
            _source = GetComponent<AudioSource>();
            _source.playOnAwake = false;
            _source.loop = false;
            _source.spatialBlend = 0f;
            _source.volume = volume;
        }

        private void OnEnable()
        {
            if (webSocketClient == null)
            {
                return;
            }
            webSocketClient.OnBinaryFrame += HandleBinaryFrame;
            webSocketClient.OnMessage += HandleEnvelope;
        }

        private void OnDisable()
        {
            if (webSocketClient == null)
            {
                return;
            }
            webSocketClient.OnBinaryFrame -= HandleBinaryFrame;
            webSocketClient.OnMessage -= HandleEnvelope;
        }

        private void HandleEnvelope(QuestEnvelope envelope)
        {
            switch (envelope.type)
            {
                case "audio.tts_start":
                    BeginSegment(envelope.payload);
                    break;
                case "audio.tts_end":
                    EndSegment(envelope.payload);
                    break;
            }
        }

        private void BeginSegment(JObject payload)
        {
            StopPlayback(false);
            ResponseId = payload.Value<string>("response_id") ?? "";
            CurrentText = payload.Value<string>("text") ?? "";
            _sampleRate = payload.Value<int?>("sample_rate") ?? 16000;
            _expectedBytes = payload.Value<int?>("total_bytes") ?? 0;
            _receivedBytes = 0;
            _writtenSamples = 0;
            _totalSamples = Mathf.Max(1, _expectedBytes / 2);
            _clipBuffer = new float[_totalSamples];
            _clip = AudioClip.Create($"qiyu_tts_{ResponseId}", _totalSamples, 1,
                _sampleRate, false);
            _finalChunkReceived = false;
            OnSpeechSegmentStart?.Invoke(CurrentText);
        }

        private void HandleBinaryFrame(byte[] payload, byte kind, uint seq)
        {
            if (kind != QuestBinaryProtocol.KindTtsOutPcm16 || _clip == null || payload == null)
            {
                return;
            }
            var samples = payload.Length / 2;
            if (_writtenSamples + samples > _totalSamples)
            {
                samples = Mathf.Max(0, _totalSamples - _writtenSamples);
            }
            for (var i = 0; i < samples; i++)
            {
                var lo = payload[i * 2];
                var hi = payload[i * 2 + 1];
                _clipBuffer[_writtenSamples + i] = (short)(lo | (hi << 8)) / 32768f;
            }
            _clip.SetData(_clipBuffer, 0);
            _writtenSamples += samples;
            _receivedBytes += payload.Length;

            var prebufferSamples = Mathf.RoundToInt(prebufferSeconds * _sampleRate);
            if (!_playing && _writtenSamples >= prebufferSamples)
            {
                StartPlayback();
            }
        }

        private void EndSegment(JObject payload)
        {
            var interrupted = payload.Value<bool?>("interrupted") ?? false;
            if (interrupted)
            {
                StopPlayback(true);
                return;
            }
            _finalChunkReceived = true;
            if (!_playing && _writtenSamples > 0)
            {
                StartPlayback();
            }
        }

        private void StartPlayback()
        {
            if (_clip == null || _playing)
            {
                return;
            }
            _source.clip = _clip;
            _source.volume = volume;
            _source.Play();
            _playing = true;
            Debug.Log($"[QuestTTS] 开始播放 {_writtenSamples} samples: {CurrentText}");
        }

        public void StopPlayback(bool notify)
        {
            var wasPlaying = _playing;
            _playing = false;
            _finalChunkReceived = false;
            MouthAmplitude = 0f;
            if (_source != null)
            {
                _source.Stop();
                _source.clip = null;
            }
            if (_clip != null)
            {
                Destroy(_clip);
                _clip = null;
            }
            _clipBuffer = null;
            if (notify && wasPlaying)
            {
                OnSpeechSegmentEnd?.Invoke(ResponseId, true);
            }
        }

        private void Update()
        {
            if (!_playing || _source == null)
            {
                return;
            }
            UpdateMouthAmplitude();
            if (!_source.isPlaying)
            {
                _playing = false;
                MouthAmplitude = 0f;
                if (_finalChunkReceived)
                {
                    OnSpeechSegmentEnd?.Invoke(ResponseId, false);
                }
            }
        }

        private void UpdateMouthAmplitude()
        {
            const int sampleCount = 256;
            if (_outputBuffer == null || _outputBuffer.Length != sampleCount)
            {
                _outputBuffer = new float[sampleCount];
            }
            _source.GetOutputData(_outputBuffer, 0);
            double sum = 0;
            for (var i = 0; i < _outputBuffer.Length; i++)
            {
                sum += _outputBuffer[i] * _outputBuffer[i];
            }
            MouthAmplitude = Mathf.Clamp01(Mathf.Sqrt((float)(sum / _outputBuffer.Length)) * 3f);
        }

        private void OnDestroy()
        {
            StopPlayback(false);
        }
    }
}
