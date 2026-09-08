using System;

namespace Qiyu.Quest.Networking
{
    /// <summary>
    /// Quest Protocol v1 二进制帧（与后端 binary_frame.py 一致）。
    /// </summary>
    public static class QuestBinaryProtocol
    {
        public const byte KindAudioInPcm16 = 1;
        public const byte KindTtsOutPcm16 = 2;
        public const byte KindVisionJpeg = 3;
        public const int HeaderSize = 8;
        private const byte Version = 1;

        public static byte[] Pack(byte kind, uint sequence, byte[] payload)
        {
            payload = payload ?? Array.Empty<byte>();
            var frame = new byte[HeaderSize + payload.Length];
            frame[0] = (byte)'Q';
            frame[1] = (byte)'Y';
            frame[2] = Version;
            frame[3] = kind;
            frame[4] = (byte)(sequence & 0xFF);
            frame[5] = (byte)((sequence >> 8) & 0xFF);
            frame[6] = (byte)((sequence >> 16) & 0xFF);
            frame[7] = (byte)((sequence >> 24) & 0xFF);
            Buffer.BlockCopy(payload, 0, frame, HeaderSize, payload.Length);
            return frame;
        }

        public static bool TryUnpack(byte[] data, out byte kind, out uint sequence, out byte[] payload)
        {
            kind = 0;
            sequence = 0;
            payload = null;
            if (data == null || data.Length < HeaderSize)
            {
                return false;
            }
            if (data[0] != (byte)'Q' || data[1] != (byte)'Y' || data[2] != Version)
            {
                return false;
            }
            kind = data[3];
            sequence = (uint)(data[4] | (data[5] << 8) | (data[6] << 16) | (data[7] << 24));
            payload = new byte[data.Length - HeaderSize];
            Buffer.BlockCopy(data, HeaderSize, payload, 0, payload.Length);
            return true;
        }
    }
}
