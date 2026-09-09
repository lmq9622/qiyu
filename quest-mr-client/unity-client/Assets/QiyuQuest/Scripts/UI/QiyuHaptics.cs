using System.Collections;
using UnityEngine;

namespace Qiyu.Quest.UI
{
    /// <summary>
    /// 短促有力的“啵”触觉反馈。
    /// OVRInput 的连续震动如果时间太长会显得拖沓，这里用三次很短的
    /// 强弱变化模拟一次点击的 pop。
    /// </summary>
    public class QiyuHaptics : MonoBehaviour
    {
        public static QiyuHaptics Instance { get; private set; }

        private Coroutine _routine;

        private void Awake()
        {
            Instance = this;
        }

        private void OnDestroy()
        {
            if (Instance == this)
            {
                Instance = null;
            }
            StopVibration();
        }

        public static void Pulse()
        {
            if (Instance == null)
            {
                var go = new GameObject("QiyuHaptics");
                Instance = go.AddComponent<QiyuHaptics>();
            }
            if (Instance._routine != null)
            {
                Instance.StopCoroutine(Instance._routine);
            }
            Instance._routine = Instance.StartCoroutine(Instance.PulseRoutine());
        }

        private IEnumerator PulseRoutine()
        {
            SetVibration(0.45f, 0.85f);
            yield return new WaitForSecondsRealtime(0.035f);
            SetVibration(0.85f, 0.25f);
            yield return new WaitForSecondsRealtime(0.02f);
            SetVibration(0.45f, 0.75f);
            yield return new WaitForSecondsRealtime(0.035f);
            StopVibration();
            _routine = null;
        }

        private static void SetVibration(float frequency, float amplitude)
        {
            OVRInput.SetControllerVibration(frequency, amplitude, OVRInput.Controller.RTouch);
            OVRInput.SetControllerVibration(frequency, amplitude, OVRInput.Controller.LTouch);
        }

        private static void StopVibration()
        {
            OVRInput.SetControllerVibration(0f, 0f, OVRInput.Controller.RTouch);
            OVRInput.SetControllerVibration(0f, 0f, OVRInput.Controller.LTouch);
        }
    }
}
