using UnityEngine;

namespace Qiyu.Quest.UI
{
    /// <summary>
    /// Meta 官方 OVRRayHelper 默认使用内置 Standard shader 的材质；
    /// 在 URP 下会显示成粉色。这里在运行时替换成 URP Unlit 的青色激光材质，
    /// 保留 Meta 官方的射线几何、cursor 和 hover/press 反馈。
    /// </summary>
    public class QiyuInteractionBootstrap : MonoBehaviour
    {
        private void Start()
        {
            ApplyRayMaterials();
        }

        public void ApplyRayMaterials()
        {
            var shader = Shader.Find("Universal Render Pipeline/Unlit")
                         ?? Shader.Find("Unlit/Color")
                         ?? Shader.Find("Sprites/Default");
            if (shader == null)
            {
                Debug.LogWarning("[QiyuInteraction] 找不到可用的 URP Unlit shader");
                return;
            }

            var normal = CreateMaterial(shader, "QiyuRayNormal",
                new Color(0.42f, 0.84f, 1f, 0.78f));
            var selected = CreateMaterial(shader, "QiyuRaySelected",
                new Color(1f, 1f, 1f, 0.95f));

            var helpers = FindObjectsByType<OVRRayHelper>(FindObjectsInactive.Include);
            foreach (var helper in helpers)
            {
                if (helper == null)
                {
                    continue;
                }
                helper.NormalMaterial = normal;
                helper.PinchMaterial = selected;
                // 官方 OVRRayHelper 的网格在输入源切换时会留下卡死的蓝条；
                // 可见激光改由 QiyuPointerVisuals 统一绘制。
                if (helper.Renderer != null)
                {
                    helper.Renderer.enabled = false;
                }
                if (helper.Cursor != null)
                {
                    foreach (var cursorRenderer in helper.Cursor.GetComponentsInChildren<Renderer>(true))
                    {
                        cursorRenderer.enabled = false;
                    }
                }
            }
            Debug.Log($"[QiyuInteraction] 已替换 {helpers.Length} 个激光材质为 URP Unlit");
        }

        private static Material CreateMaterial(Shader shader, string name, Color color)
        {
            var material = new Material(shader) { name = name };
            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", color);
            }
            if (material.HasProperty("_Color"))
            {
                material.SetColor("_Color", color);
            }
            if (material.HasProperty("_Surface"))
            {
                material.SetFloat("_Surface", 1f); // transparent
            }
            if (material.HasProperty("_Blend"))
            {
                material.SetFloat("_Blend", 0f); // alpha blend
            }
            if (material.HasProperty("_ZWrite"))
            {
                material.SetFloat("_ZWrite", 0f);
            }
            material.renderQueue = 3000;
            return material;
        }
    }
}
