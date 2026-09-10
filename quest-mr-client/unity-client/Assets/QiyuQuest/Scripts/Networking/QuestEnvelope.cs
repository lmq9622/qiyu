using System;
using Newtonsoft.Json.Linq;

namespace Qiyu.Quest.Networking
{
    /// <summary>
    /// Quest Protocol v1 Envelope。
    /// payload 使用 JObject，兼容 WorldState / AvatarIntent / SpatialAction 后续类型。
    /// </summary>
    [Serializable]
    public sealed class QuestEnvelope
    {
        public string v = "1.0.0";
        public string id = Guid.NewGuid().ToString("N");
        public string type = "";
        public long ts;
        public string session = "";
        public string reply_to = "";
        public int seq;
        public int ack;
        public JObject payload = new JObject();

        public QuestEnvelope() { }

        public QuestEnvelope(string type, JObject payload, string session = "",
                             string replyTo = "", int seq = 0, int ack = 0)
        {
            this.type = type;
            this.payload = payload ?? new JObject();
            this.session = session;
            this.reply_to = replyTo;
            this.seq = Math.Max(0, seq);
            this.ack = Math.Max(0, ack);
            this.ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        }

        public static QuestEnvelope FromJson(string json)
        {
            var envelope = Newtonsoft.Json.JsonConvert.DeserializeObject<QuestEnvelope>(json);
            if (envelope == null)
            {
                throw new InvalidOperationException("无法解析 QuestEnvelope");
            }
            envelope.payload = envelope.payload ?? new JObject();
            return envelope;
        }

        public string ToJson()
        {
            return Newtonsoft.Json.JsonConvert.SerializeObject(this);
        }

        public QuestEnvelope Reply(string replyType, JObject replyPayload)
        {
            return new QuestEnvelope(replyType, replyPayload, session, id, 0, seq);
        }
    }
}
