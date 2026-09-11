using System;
using System.Text;
using System.Threading.Tasks;
using NativeWebSocket;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace Qiyu.Quest.Networking
{
    /// <summary>
    /// Quest ↔ Qiyu Gateway 协议 v1 客户端。
    /// 复用 NativeWebSocket（MIT），不自行实现底层 WebSocket；
    /// 负责握手、心跳、自动重连、barge_in 与消息分发。
    /// </summary>
    public class QiyuQuestWebSocketClient : MonoBehaviour
    {
        [Header("连接")]
        [SerializeField] private string serverUrl =
            "ws://192.168.1.100:8766/v1/quest/ws";
        [SerializeField] private string userId = "quest_user";
        [SerializeField] private string charId = "xiaoban";
        [SerializeField] private string deviceName = "meta-quest-3";
        [SerializeField] private string clientVersion = "0.2.0";

        [Header("心跳与重连")]
        [SerializeField] private float heartbeatIntervalSeconds = 5f;
        [SerializeField] private bool autoReconnect = true;
        [SerializeField] private float reconnectMinDelaySeconds = 1f;
        [SerializeField] private float reconnectMaxDelaySeconds = 15f;
        [SerializeField] private bool persistServerUrl = true;

        private const string ServerUrlPrefKey = "qiyu.quest.server_url";

        private WebSocket _socket;
        private string _sessionId = "";
        private bool _handshakeDone;
        private float _lastHeartbeatAt;
        private float _nextReconnectAt;
        private float _reconnectDelay;
        private bool _connecting;
        private bool _quitting;
        private int _clientSequence;
        private int _lastServerSequence;
        private int _lastAckedServerSequence;

        public event Action<QuestEnvelope> OnMessage;
        public event Action<bool> OnConnectionChanged;
        public event Action SessionEstablished;
        public event Action<JObject> OnAgentSpeech;
        public event Action<JObject> OnAvatarIntent;
        /// <summary>Behavior 层：计划 / 单个动作 / 动作事件 / 状态快照。</summary>
        public event Action<JObject> OnBehaviorPlan;
        public event Action<JObject> OnBehaviorAction;
        public event Action<JObject> OnBehaviorEvent;
        public event Action<JObject> OnBehaviorState;
        public event Action<JObject> OnSpatialAction;
        public event Action<JObject> OnCharacterState;
        public event Action<JObject> OnAutonomyResult;
        public event Action<JObject> OnServerAck;
        /// <summary>二进制帧：payload, kind, seq</summary>
        public event Action<byte[], byte, uint> OnBinaryFrame;

        public bool IsConnected => _socket != null && _socket.State == WebSocketState.Open;
        public bool HandshakeDone => _handshakeDone;
        public string SessionId => _sessionId;
        public string ServerUrl => serverUrl;
        public int ClientSequence => _clientSequence;
        public int LastServerSequence => _lastServerSequence;

        private async void Start()
        {
            if (persistServerUrl)
            {
                var saved = PlayerPrefs.GetString(ServerUrlPrefKey, "");
                if (!string.IsNullOrWhiteSpace(saved))
                {
                    serverUrl = saved;
                }
            }
            _reconnectDelay = reconnectMinDelaySeconds;
            await ConnectAsync();
        }

        public void SetServerUrl(string url, bool reconnect = true)
        {
            if (string.IsNullOrWhiteSpace(url))
            {
                return;
            }
            serverUrl = url.Trim();
            if (persistServerUrl)
            {
                PlayerPrefs.SetString(ServerUrlPrefKey, serverUrl);
                PlayerPrefs.Save();
            }
            if (reconnect)
            {
                _ = ConnectAsync();
            }
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
            TryReconnect();
        }

        public async Task ConnectAsync()
        {
            if (_connecting)
            {
                return;
            }
            _connecting = true;
            try
            {
                await DisconnectAsync(sendBye: false);
                _socket = new WebSocket(serverUrl);
                _socket.OnOpen += HandleOpen;
                _socket.OnMessage += HandleMessage;
                _socket.OnError += HandleError;
                _socket.OnClose += HandleClose;
                OnConnectionChanged?.Invoke(false);
                await _socket.Connect();
                _reconnectDelay = reconnectMinDelaySeconds;
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[QuestWS] 连接失败: {e.Message}");
                ScheduleReconnect();
            }
            finally
            {
                _connecting = false;
            }
        }

        public async Task DisconnectAsync(bool sendBye = true)
        {
            if (_socket == null)
            {
                return;
            }
            try
            {
                if (sendBye && _socket.State == WebSocketState.Open &&
                    !string.IsNullOrEmpty(_sessionId))
                {
                    var bye = new QuestEnvelope("client.bye", new JObject(), _sessionId);
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
            _clientSequence = 0;
            _lastServerSequence = 0;
            _lastAckedServerSequence = 0;
        }

        public Task SendAsync(QuestEnvelope envelope)
        {
            if (envelope == null)
            {
                return Task.CompletedTask;
            }
            if (_socket == null || _socket.State != WebSocketState.Open)
            {
                Debug.LogWarning("[QuestWS] 连接未打开，丢弃消息");
                return Task.CompletedTask;
            }
            if (envelope.seq <= 0)
            {
                envelope.seq = ++_clientSequence;
            }
            if (envelope.ack <= 0)
            {
                envelope.ack = _lastServerSequence;
            }
            return _socket.SendText(envelope.ToJson());
        }

        public Task SendUserTextAsync(string text)
        {
            if (string.IsNullOrWhiteSpace(text))
            {
                return Task.CompletedTask;
            }
            var payload = new JObject { ["text"] = text };
            return SendAsync(new QuestEnvelope("user.text", payload, _sessionId));
        }

        public Task SendBargeInAsync(string reason = "")
        {
            var payload = new JObject { ["reason"] = reason ?? "" };
            return SendAsync(new QuestEnvelope("client.barge_in", payload, _sessionId));
        }

        public Task SendWorldStateAsync(JObject worldState)
        {
            return SendAsync(new QuestEnvelope("client.world_state",
                worldState ?? new JObject(), _sessionId));
        }

        public Task SendWorldStateDeltaAsync(JObject delta)
        {
            return SendAsync(new QuestEnvelope("client.world_state_delta",
                delta ?? new JObject(), _sessionId));
        }

        public Task SendBehaviorStateAsync(JObject behaviorState)
        {
            return SendAsync(new QuestEnvelope("client.behavior_state",
                behaviorState ?? new JObject(), _sessionId));
        }

        public Task SendCharacterStateAsync(JObject characterState)
        {
            return SendAsync(new QuestEnvelope("client.character_state",
                characterState ?? new JObject(), _sessionId));
        }

        public Task SendInteractionEventAsync(string eventType, string targetId = "",
                                              float value = 0f, JObject data = null)
        {
            var payload = new JObject
            {
                ["schema_version"] = "1.1",
                ["ts"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["event_type"] = eventType ?? "",
                ["target_id"] = targetId ?? "",
                ["value"] = value,
                ["data"] = data ?? new JObject()
            };
            return SendAsync(new QuestEnvelope("client.interaction_event",
                payload, _sessionId));
        }

        public Task SendHumanMotionStateAsync(JObject motionState)
        {
            return SendAsync(new QuestEnvelope("client.human_motion_state",
                motionState ?? new JObject(), _sessionId));
        }

        public Task SendGestureEventAsync(string gesture, string intent,
                                          string targetId, float confidence,
                                          Vector3 direction, float distance,
                                          string emotionHint = "")
        {
            var payload = new JObject
            {
                ["schema_version"] = "1.1",
                ["ts"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["event_type"] = "gesture",
                ["target_id"] = targetId ?? "",
                ["value"] = confidence,
                ["gesture"] = gesture ?? "",
                ["intent"] = intent ?? "",
                ["confidence"] = Mathf.Clamp01(confidence),
                ["distance_m"] = distance,
                ["emotion_hint"] = emotionHint ?? "",
                ["source"] = "local_motion_understanding",
                ["direction"] = new JObject
                {
                    ["x"] = direction.x,
                    ["y"] = direction.y,
                    ["z"] = direction.z
                },
                ["data"] = new JObject()
            };
            return SendAsync(new QuestEnvelope("client.interaction_event",
                payload, _sessionId));
        }

        public Task SendAutonomyRequestAsync(string reason, float urgency = 0f,
                                             float socialPriority = 0.5f,
                                             int cooldownSeconds = 90,
                                             int sceneVersion = 0)
        {
            var payload = new JObject
            {
                ["schema_version"] = "1.1",
                ["reason"] = reason ?? "",
                ["urgency"] = Mathf.Clamp01(urgency),
                ["social_priority"] = Mathf.Clamp01(socialPriority),
                ["cooldown_s"] = Mathf.Clamp(cooldownSeconds, 5, 3600),
                ["world_scene_version"] = Mathf.Max(0, sceneVersion)
            };
            return SendAsync(new QuestEnvelope("client.autonomy_request",
                payload, _sessionId));
        }

        public Task SendBinaryAsync(byte[] data)
        {
            if (data == null || data.Length == 0)
            {
                return Task.CompletedTask;
            }
            if (_socket == null || _socket.State != WebSocketState.Open)
            {
                Debug.LogWarning("[QuestWS] 连接未打开，丢弃二进制帧");
                return Task.CompletedTask;
            }
            return _socket.Send(data);
        }

        private void HandleOpen()
        {
            Debug.Log($"[QuestWS] 已连接 {serverUrl}");
            _clientSequence = 0;
            _lastServerSequence = 0;
            _lastAckedServerSequence = 0;
            OnConnectionChanged?.Invoke(true);
            var capabilities = new JArray
            {
                "world_state_v1", "avatar_intent_v1", "spatial_action_v1",
                "character_schema_v1_1", "behavior_state_v1_1",
                "interaction_events_v1_1", "autonomy_request_v1_1",
                "world_state_delta_v1_1", "user.text", "barge_in",
                "behavior_v1", "behavior_plan_v1"
            };
            var payload = new JObject
            {
                ["user_id"] = string.IsNullOrWhiteSpace(userId) ? "quest_user" : userId,
                ["char_id"] = string.IsNullOrWhiteSpace(charId) ? "xiaoban" : charId,
                ["device"] = deviceName,
                ["client_version"] = clientVersion,
                ["capabilities"] = capabilities
            };
            var hello = new QuestEnvelope("client.hello", payload);
            var json = hello.ToJson();
            Debug.Log($"[QuestWS] hello={json}");
            if (_socket != null && _socket.State == WebSocketState.Open)
            {
                _ = _socket.SendText(json);
            }
            else
            {
                _ = SendAsync(hello);
            }
        }

        private void HandleMessage(byte[] bytes)
        {
            if (bytes != null && bytes.Length >= 2 && bytes[0] == (byte)'Q' && bytes[1] == (byte)'Y')
            {
                if (QuestBinaryProtocol.TryUnpack(bytes, out var kind, out var seq, out var payload))
                {
                    OnBinaryFrame?.Invoke(payload, kind, seq);
                }
                return;
            }
            try
            {
                var json = Encoding.UTF8.GetString(bytes);
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
            if (envelope.seq > 0)
            {
                if (envelope.seq < _lastServerSequence)
                {
                    Debug.LogWarning(
                        $"[QuestWS] 丢弃乱序旧消息 {envelope.type} seq={envelope.seq} " +
                        $"last={_lastServerSequence}");
                    return;
                }
                _lastServerSequence = envelope.seq;
            }
            if (envelope.ack > _lastAckedServerSequence)
            {
                _lastAckedServerSequence = envelope.ack;
            }
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
                case "agent.speech":
                    OnAgentSpeech?.Invoke(envelope.payload);
                    break;
                case "avatar.intent":
                    OnAvatarIntent?.Invoke(envelope.payload);
                    break;
                case "spatial.action":
                    OnSpatialAction?.Invoke(envelope.payload);
                    break;
                case "server.behavior_plan":
                    Debug.Log($"[QuestWS] behavior plan intent=" +
                              $"{envelope.payload.Value<string>("intent")}");
                    OnBehaviorPlan?.Invoke(envelope.payload);
                    break;
                case "server.behavior_action":
                    OnBehaviorAction?.Invoke(envelope.payload);
                    break;
                case "server.behavior_event":
                    OnBehaviorEvent?.Invoke(envelope.payload);
                    break;
                case "server.behavior_state":
                    OnBehaviorState?.Invoke(envelope.payload);
                    break;
                case "character.state":
                    OnCharacterState?.Invoke(envelope.payload);
                    break;
                case "server.autonomy_result":
                    OnAutonomyResult?.Invoke(envelope.payload);
                    break;
                case "server.ack":
                    OnServerAck?.Invoke(envelope.payload);
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

        private void TryReconnect()
        {
            if (!autoReconnect || _quitting || _connecting || IsConnected)
            {
                return;
            }
            if (Time.unscaledTime < _nextReconnectAt)
            {
                return;
            }
            Debug.Log($"[QuestWS] 尝试重连（{_reconnectDelay:F1}s 退避）");
            _ = ConnectAsync();
        }

        private void ScheduleReconnect()
        {
            if (!autoReconnect || _quitting)
            {
                return;
            }
            _nextReconnectAt = Time.unscaledTime + _reconnectDelay;
            _reconnectDelay = Mathf.Min(_reconnectDelay * 1.7f, reconnectMaxDelaySeconds);
        }

        private void HandleError(string error)
        {
            Debug.LogError($"[QuestWS] 错误: {error}");
            ScheduleReconnect();
        }

        private void HandleClose(WebSocketCloseCode code)
        {
            Debug.Log($"[QuestWS] 已断开: {code}");
            _sessionId = "";
            _handshakeDone = false;
            _clientSequence = 0;
            _lastServerSequence = 0;
            _lastAckedServerSequence = 0;
            OnConnectionChanged?.Invoke(false);
            ScheduleReconnect();
        }

        private async void OnApplicationQuit()
        {
            _quitting = true;
            await DisconnectAsync();
        }

        private void OnDestroy()
        {
            _quitting = true;
        }
    }
}


