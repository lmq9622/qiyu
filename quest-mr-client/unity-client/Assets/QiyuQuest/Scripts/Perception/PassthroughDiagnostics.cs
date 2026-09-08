using System.Text;
using Meta.XR.MRUtilityKit;
using UnityEngine;

namespace Qiyu.Quest.Perception
{
    /// <summary>
    /// 真机诊断：把 OVRManager / OVRPassthroughLayer / 相机的真实运行状态打到 logcat。
    /// 只在排查 MR 显示问题时使用，不影响功能。
    /// </summary>
    public class PassthroughDiagnostics : MonoBehaviour
    {
        [SerializeField] private float intervalSeconds = 5f;
        public static string LastSnapshot { get; private set; } = "";

        private void Start()
        {
            InvokeRepeating(nameof(LogState), 2f, Mathf.Max(1f, intervalSeconds));
        }

        private void LogState()
        {
            var manager = OVRManager.instance;
            var layers = FindObjectsByType<OVRPassthroughLayer>(
                FindObjectsInactive.Include, FindObjectsSortMode.None);
            var builder = new StringBuilder();
            foreach (var layer in layers)
            {
                if (layer == null)
                {
                    continue;
                }
                builder.Append($"[{layer.gameObject.name}:enabled={layer.enabled}," +
                               $"hidden={layer.hidden},overlay={layer.overlayType}]");
            }
            var centerEye = GameObject.Find("CenterEyeAnchor");
            var camera = centerEye != null ? centerEye.GetComponent<Camera>() : null;
            var room = MRUK.Instance != null ? MRUK.Instance.GetCurrentRoom() : null;
            LastSnapshot =
                $"manager={(manager != null)} " +
                $"wantPT={(manager != null && manager.isInsightPassthroughEnabled)} " +
                $"supported={OVRManager.IsInsightPassthroughSupported()} " +
                $"initialized={OVRManager.IsInsightPassthroughInitialized()} " +
                $"layers={layers.Length}{builder} " +
                $"camera={(camera != null)} clear={camera?.clearFlags} bg={camera?.backgroundColor} " +
                $"mrukRoom={(room != null ? room.name : "none")} " +
                $"anchors={(room != null ? room.Anchors.Count : 0)}";
            Debug.Log("[PassthroughDiag] " + LastSnapshot);
        }
    }
}
