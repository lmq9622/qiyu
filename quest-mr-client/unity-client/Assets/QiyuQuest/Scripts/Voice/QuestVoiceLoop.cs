using Qiyu.Quest.Networking;
using UnityEngine;

namespace Qiyu.Quest.Voice
{
    /// <summary>
    /// 语音闭环编排：麦克风 VAD → 二进制上行 → 服务端 STT/大脑/TTS → 客户端播放。
    /// 打断：用户说话 → client.barge_in + 立即停止本地 TTS 播放。
    /// </summary>
    public class QuestVoiceLoop : MonoBehaviour
    {
        [SerializeField] private QiyuQuestWebSocketClient webSocketClient;
        [SerializeField] private QuestMicrophoneCapture microphone;
        [SerializeField] private QuestTtsPlayer ttsPlayer;
        [SerializeField] private bool enableBargeIn = true;

        public bool LastTurnInterrupted { get; private set; }

        private void OnEnable()
        {
            if (microphone != null)
            {
                microphone.IsTtsPlaying = () => ttsPlayer != null && ttsPlayer.IsPlaying;
                microphone.OnBargeInDetected += HandleBargeIn;
            }
            if (webSocketClient != null)
            {
                webSocketClient.OnAgentSpeech += HandleAgentSpeech;
            }
        }

        private void OnDisable()
        {
            if (microphone != null)
            {
                microphone.OnBargeInDetected -= HandleBargeIn;
            }
            if (webSocketClient != null)
            {
                webSocketClient.OnAgentSpeech -= HandleAgentSpeech;
            }
        }

        private void HandleBargeIn()
        {
            if (!enableBargeIn)
            {
                return;
            }
            LastTurnInterrupted = true;
            if (ttsPlayer != null)
            {
                ttsPlayer.StopPlayback(true);
            }
            if (webSocketClient != null)
            {
                _ = webSocketClient.SendBargeInAsync("user_speech");
            }
            Debug.Log("[QuestVoice] 用户插话，已打断 TTS");
        }

        private void HandleAgentSpeech(Newtonsoft.Json.Linq.JObject payload)
        {
            LastTurnInterrupted = false;
        }

        /// <summary>文本输入（编辑器/无障碍/调试用），与语音走同一条后端链路。</summary>
        public void SendText(string text)
        {
            if (webSocketClient != null)
            {
                _ = webSocketClient.SendUserTextAsync(text);
            }
        }
    }
}
