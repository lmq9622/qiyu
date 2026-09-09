using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR;

namespace Qiyu.Quest.UI
{
    /// <summary>
    /// Quest 端渲染质量控制。
    ///
    /// 头显里“晃动时边缘锯齿严重”通常不是 UI 贴图本身，而是三件事叠加：
    ///   1. 渲染分辨率偏低（动态分辨率 / renderScale &lt; 1）；
    ///   2. 高等级注视点渲染把周边像素压得太狠；
    ///   3. 世界空间文字用旧版位图字体，缩放后发糊、闪烁。
    /// 第 3 点由 TMP SDF + mipmap 解决；这里负责 1、2 与 MSAA。
    /// </summary>
    public class QiyuRenderQuality : MonoBehaviour
    {
        private bool _started;

        private void Start()
        {
            if (!_started)
            {
                StartCoroutine(ApplyWhenXrReady());
            }
        }

        public void ApplyFromSettings()
        {
            var scale = Mathf.Clamp(QiyuSettings.RenderScale, 1f, 1.4f);
            QualitySettings.antiAliasing = 4;
            QualitySettings.vSyncCount = 0;

            // Unity 6 推荐用 XRDisplaySubsystem.scaleOfAllRenderTargets；
            // 用反射调用，兼容不同 XR 插件版本。
            var displays = new List<XRDisplaySubsystem>();
            SubsystemManager.GetSubsystems(displays);
            foreach (var display in displays)
            {
                if (display == null)
                {
                    continue;
                }
                var property = typeof(XRDisplaySubsystem).GetProperty("scaleOfAllRenderTargets");
                if (property != null && property.CanWrite)
                {
                    property.SetValue(display, scale);
                }
            }

#pragma warning disable CS0618
            XRSettings.eyeTextureResolutionScale = scale;
#pragma warning restore CS0618

            ApplyFoveation();
            Debug.Log($"[QiyuRenderQuality] renderScale={scale:0.00} " +
                      $"foveation={(QiyuSettings.LowFoveation ? "Low" : "Off")} MSAA=4");
        }

        private void ApplyFoveation()
        {
            try
            {
                if (OVRManager.instance == null)
                {
                    return;
                }
                OVRManager.foveatedRenderingLevel = QiyuSettings.LowFoveation
                    ? OVRManager.FoveatedRenderingLevel.Low
                    : OVRManager.FoveatedRenderingLevel.Off;
                OVRManager.useDynamicFoveatedRendering = false;
            }
            catch (System.Exception e)
            {
                Debug.LogWarning("[QiyuRenderQuality] 设置注视点渲染失败: " + e.Message);
            }
        }

        private IEnumerator ApplyWhenXrReady()
        {
            var deadline = Time.unscaledTime + 6f;
            while (OVRManager.instance == null && Time.unscaledTime < deadline)
            {
                yield return null;
            }
            _started = true;
            ApplyFromSettings();
        }
    }
}
