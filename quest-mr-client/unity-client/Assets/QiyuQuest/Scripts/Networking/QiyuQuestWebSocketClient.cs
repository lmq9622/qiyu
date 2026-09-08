using System;
using System.Text;
using System.Threading.Tasks;
using NativeWebSocket;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace Qiyu.Quest.Networking
{
    /// <summary>
    /// 复用 NativeWebSocket（MIT），不自行实现底层 WebSocket。
    /// P0 只实现 hello/heartbeat/echo/bye；其余消息由后续 Handler 扩展。
    /// </summary>
    public class QiyuQuestWebSocketClient : MonoBehaviour
    {
        [Header("连接")]
        [SerializeField] private string serverUrl =
            "ws://192.168.1.100:8766/v1/quest/ws";
        [SerializeField] private string userId = "quest_user";
        [SerializeField] private string charId = "xiaoban";
        [SerializeField] private float heartbeatIntervalSeconds = 5f;

        private WebSocket _socket;
        private string _sessionId = "";
        private bool _handshakeDone;
        private float _lastHeartbeatAt;

        public event Action<QuestEnvelope> OnMessage;
        public event Action<bool> OnConnectionChanged;
        public event Action SessionEstablished;

        public bool IsConnected => _socket != null && _socket.State == WebSocketState.Open;
        public bool HandshakeDone => _handshakeDone;
        public string SessionId => _sessionId;

        private async void Start()
        {
            await ConnectAsync();
        }

        private void Update()
        {
#if !UNITY_WEBGL
            if (_socket != null)
            {
                _socket.DispatchMessageQueue();
            }
#endif
            TrySendHeartbeat();
        }

        public async Task ConnectAsync()
        {
            await DisconnectAsync();
            _socket = new WebSocket(serverUrl);
            _socket.OnOpen += HandleOpen;
            _socket.OnMessage += HandleMessage;
            _socket.OnError += HandleError;
            _socket.OnClose += HandleClose;
            OnConnectionChanged?.Invoke(false);
            await _socket.Connect();
        }

        public async Task DisconnectAsync()
        {
            if (_socket == null)
            {
                return;
            }
            try
            {
                if (_socket.State == WebSocketState.Open && !string.IsNullOrEmpty(_sessionId))
                {
                    var bye = new QuestEnvelope(
                        "client.bye",
                        new JObject(),
                        _sessionId);
                    await SendAsync(bye);
                }
                await _socket.Close();
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[QuestWS] 关闭连接异常: {e.Message}");
            }
            _socket = null;
            _sessionId = "";
            _handshakeDone = false;
        }

        public Task SendAsync(QuestEnvelope envelope)
        {
            if (_socket == null || _socket.State != WebSocketState.Open)
            {
                Debug.LogWarning("[QuestWS] 连接未打开，丢弃消息");
                return Task.CompletedTask;
            }
            return _socket.SendText(envelope.ToJson());
        }

        private void HandleOpen()
        {
            Debug.Log("[QuestWS] 已连接");
            OnConnectionChanged?.Invoke(true);
            var hello = new QuestEnvelope("client.hello", JObject.FromObject(new
            {
                user_id = userId,
                char_id = charId,
                device = "meta-quest-3",
                client_version = "0.0.1",
                capabilities = new[] { "world_state_v1" }
            }));
            _ = SendAsync(hello);
        }

        private void HandleMessage(byte[] bytes)
        {
            string json;
            try
            {
                json = Encoding.UTF8.GetString(bytes);
                var envelope = QuestEnvelope.FromJson(json);
                Dispatch(envelope);
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[QuestWS] 消息解析失败: {e.Message}");
            }
        }

        private void Dispatch(QuestEnvelope envelope)
        {
            switch (envelope.type)
            {
                case "server.hello_ack":
                    _sessionId = envelope.payload.Value<string>("session_id") ?? envelope.session;
                    _handshakeDone = !string.IsNullOrEmpty(_sessionId);
                    Debug.Log($"[QuestWS] session 建立: {_sessionId}");
                    SessionEstablished?.Invoke();
                    break;
                case "server.heartbeat":
                    _lastHeartbeatAt = Time.unscaledTime;
                    break;
                case "server.error":
                    Debug.LogWarning(
                        $"[QuestWS] 服务端错误: {envelope.payload.Value<string>("code")} " +
                        $"{envelope.payload.Value<string>("message")}");
                    break;
            }
            OnMessage?.Invoke(envelope);
        }

        private void TrySendHeartbeat()
        {
            if (!_handshakeDone || !IsConnected)
            {
                return;
            }
            if (Time.unscaledTime - _lastHeartbeatAt < heartbeatIntervalSeconds)
            {
                return;
            }
            _lastHeartbeatAt = Time.unscaledTime;
            _ = SendAsync(new QuestEnvelope("client.heartbeat", new JObject(), _sessionId));
        }

        private void HandleError(string error)
        {
            Debug.LogError($"[QuestWS] 错误: {error}");
        }

        private void HandleClose(WebSocketCloseCode code)
        {
            Debug.Log($"[QuestWS] 已断开: {code}");
            _sessionId = "";
            _handshakeDone = false;
            OnConnectionChanged?.Invoke(false);
        }

        private async void OnApplicationQuit()
        {
            await DisconnectAsync();
        }
    }
}
