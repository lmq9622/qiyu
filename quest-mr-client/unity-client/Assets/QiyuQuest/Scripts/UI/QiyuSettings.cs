using UnityEngine;

namespace Qiyu.Quest.UI
{
    public enum QiyuPanelMode
    {
        Motion3DoF = 0,
        Fixed6DoF = 1
    }

    /// <summary>Quest 端设置（PlayerPrefs 持久化）。</summary>
    public static class QiyuSettings
    {
        private const string Prefix = "qiyu.quest.";

        public static string GatewayUrl
        {
            get => PlayerPrefs.GetString(Prefix + "gateway", "ws://192.168.2.68:8766/v1/quest/ws");
            set => Set(Prefix + "gateway", value);
        }

        public static string UserId
        {
            get => PlayerPrefs.GetString(Prefix + "user_id", "quest_user");
            set => Set(Prefix + "user_id", value);
        }

        public static string CharId
        {
            get => PlayerPrefs.GetString(Prefix + "char_id", "xiaoban");
            set => Set(Prefix + "char_id", value);
        }

        public static float Temperature
        {
            get => PlayerPrefs.GetFloat(Prefix + "temperature", 0.7f);
            set => Set(Prefix + "temperature", Mathf.Clamp(value, 0f, 1.5f));
        }

        public static bool TtsEnabled
        {
            get => PlayerPrefs.GetInt(Prefix + "tts", 1) == 1;
            set => Set(Prefix + "tts", value ? 1 : 0);
        }

        public static string Voice
        {
            get => PlayerPrefs.GetString(Prefix + "voice", "");
            set => Set(Prefix + "voice", value);
        }

        public static float VadThreshold
        {
            get => PlayerPrefs.GetFloat(Prefix + "vad", 0.02f);
            set => Set(Prefix + "vad", Mathf.Clamp(value, 0.005f, 0.2f));
        }

        public static float MicGain
        {
            get => PlayerPrefs.GetFloat(Prefix + "mic_gain", 1f);
            set => Set(Prefix + "mic_gain", Mathf.Clamp(value, 0.2f, 4f));
        }

        public static string AvatarUrl
        {
            get => PlayerPrefs.GetString(Prefix + "avatar_url", "");
            set => Set(Prefix + "avatar_url", value);
        }

        public static float AvatarScale
        {
            get => PlayerPrefs.GetFloat(Prefix + "avatar_scale", 1f);
            set => Set(Prefix + "avatar_scale", Mathf.Clamp(value, 0.3f, 2.5f));
        }

        public static float AvatarHeight
        {
            get => PlayerPrefs.GetFloat(Prefix + "avatar_height", 0f);
            set => Set(Prefix + "avatar_height", Mathf.Clamp(value, -1f, 1f));
        }

        public static float AvatarRotation
        {
            get => PlayerPrefs.GetFloat(Prefix + "avatar_rotation", 0f);
            set => Set(Prefix + "avatar_rotation", Mathf.Clamp(value, -180f, 180f));
        }

        public static float RenderScale
        {
            get => PlayerPrefs.GetFloat(Prefix + "render_scale", 1.25f);
            set => Set(Prefix + "render_scale", Mathf.Clamp(value, 1f, 1.4f));
        }

        public static bool LowFoveation
        {
            get => PlayerPrefs.GetInt(Prefix + "low_foveation", 1) == 1;
            set => Set(Prefix + "low_foveation", value ? 1 : 0);
        }

        public static float PanelDistance
        {
            get => PlayerPrefs.GetFloat(Prefix + "panel_distance", 1.7f);
            set => Set(Prefix + "panel_distance", Mathf.Clamp(value, 1.2f, 3f));
        }

        public static int PanelMode
        {
            get => PlayerPrefs.GetInt(Prefix + "panel_mode", (int)QiyuPanelMode.Fixed6DoF);
            set => Set(Prefix + "panel_mode", Mathf.Clamp(value, 0, 1));
        }

        public static bool AutoConnect
        {
            get => PlayerPrefs.GetInt(Prefix + "auto_connect", 1) == 1;
            set => Set(Prefix + "auto_connect", value ? 1 : 0);
        }

        public static void ResetAll()
        {
            PlayerPrefs.DeleteKey(Prefix + "gateway");
            PlayerPrefs.DeleteKey(Prefix + "user_id");
            PlayerPrefs.DeleteKey(Prefix + "char_id");
            PlayerPrefs.DeleteKey(Prefix + "temperature");
            PlayerPrefs.DeleteKey(Prefix + "tts");
            PlayerPrefs.DeleteKey(Prefix + "voice");
            PlayerPrefs.DeleteKey(Prefix + "vad");
            PlayerPrefs.DeleteKey(Prefix + "mic_gain");
            PlayerPrefs.DeleteKey(Prefix + "avatar_url");
            PlayerPrefs.DeleteKey(Prefix + "avatar_scale");
            PlayerPrefs.DeleteKey(Prefix + "avatar_height");
            PlayerPrefs.DeleteKey(Prefix + "avatar_rotation");
            PlayerPrefs.DeleteKey(Prefix + "render_scale");
            PlayerPrefs.DeleteKey(Prefix + "low_foveation");
            PlayerPrefs.DeleteKey(Prefix + "panel_distance");
            PlayerPrefs.DeleteKey(Prefix + "panel_mode");
            PlayerPrefs.DeleteKey(Prefix + "auto_connect");
            PlayerPrefs.Save();
        }

        private static void Set(string key, string value)
        {
            PlayerPrefs.SetString(key, value ?? "");
            PlayerPrefs.Save();
        }

        private static void Set(string key, float value)
        {
            PlayerPrefs.SetFloat(key, value);
            PlayerPrefs.Save();
        }

        private static void Set(string key, int value)
        {
            PlayerPrefs.SetInt(key, value);
            PlayerPrefs.Save();
        }
    }
}
