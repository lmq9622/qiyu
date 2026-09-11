using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace Qiyu.Quest.Editor
{
    /// <summary>
    /// 把 MMD 材质与贴图显式绑定起来。
    ///
    /// 为什么需要：Unity 导入 FBX 时不会把 MMD 的中文贴图引用绑到材质上
    /// （导入后 `m_Texture` 全是 0，模型看起来是白模），
    /// 所以由 Blender 侧导出 `材质→贴图` 映射，这里按键值显式赋值。
    /// </summary>
    public static class QiyuAvatarMaterialBinder
    {
        private const string AvatarDir = "Assets/QiyuQuest/Resources/Qiyu/Avatar";
        private const string MapPath = AvatarDir + "/QiyuAvatarModel.materials.json";
        private const string MaterialDir = AvatarDir + "/Materials";
        private const string TextureDir = AvatarDir + "/QiyuAvatarModel.fbm";

        [Serializable]
        private class MaterialMapEntry
        {
            public string material;
            public string texture;
            public string file;
        }

        [Serializable]
        private class MaterialMap
        {
            public List<MaterialMapEntry> items = new List<MaterialMapEntry>();
        }

        [MenuItem("Qiyu/绑定角色材质贴图")]
        public static void BindAll()
        {
            var mapAsset = AssetDatabase.LoadAssetAtPath<TextAsset>(MapPath);
            if (mapAsset == null)
            {
                Debug.LogWarning($"[QiyuAvatarMat] 找不到材质映射 {MapPath}（跳过，不改动现有材质）");
                return;
            }
            var entries = ParseMap(mapAsset.text);
            if (entries.Count == 0)
            {
                Debug.LogWarning("[QiyuAvatarMat] 材质映射为空");
                return;
            }
            var textures = LoadTextures();
            var bound = 0;
            var missing = new List<string>();
            foreach (var entry in entries)
            {
                var materialPath = $"{MaterialDir}/{entry.material}.mat";
                var material = AssetDatabase.LoadAssetAtPath<Material>(materialPath);
                if (material == null)
                {
                    missing.Add($"材质缺失:{entry.material}");
                    continue;
                }
                if (!textures.TryGetValue(entry.file, out var texture) || texture == null)
                {
                    missing.Add($"贴图缺失:{entry.file}");
                    continue;
                }
                Assign(material, texture);
                EditorUtility.SetDirty(material);
                bound++;
            }
            AssetDatabase.SaveAssets();
            Debug.Log($"[QiyuAvatarMat] 已绑定 {bound}/{entries.Count} 个材质贴图" +
                      (missing.Count > 0 ? $"，问题项 {missing.Count}: {string.Join(",", missing.GetRange(0, Mathf.Min(5, missing.Count)))}" : ""));
        }

        private static void Assign(Material material, Texture2D texture)
        {
            // URP Lit 用 _BaseMap，内置管线/旧 shader 用 _MainTex；两个都设，避免白模
            if (material.HasProperty("_BaseMap"))
            {
                material.SetTexture("_BaseMap", texture);
            }
            if (material.HasProperty("_MainTex"))
            {
                material.SetTexture("_MainTex", texture);
            }
            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", Color.white);
            }
            if (material.HasProperty("_Color"))
            {
                material.SetColor("_Color", Color.white);
            }
            if (material.HasProperty("_Smoothness"))
            {
                material.SetFloat("_Smoothness", 0.2f);
            }
        }

        private static Dictionary<string, Texture2D> LoadTextures()
        {
            var result = new Dictionary<string, Texture2D>(StringComparer.OrdinalIgnoreCase);
            foreach (var guid in AssetDatabase.FindAssets("t:Texture2D", new[] { TextureDir }))
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
                if (texture != null)
                {
                    result[Path.GetFileName(path)] = texture;
                }
            }
            return result;
        }

        private static List<MaterialMapEntry> ParseMap(string json)
        {
            // 映射文件是数组；用最小包装避免额外依赖
            var wrapped = "{\"items\":" + json + "}";
            var parsed = JsonUtility.FromJson<MaterialMap>(wrapped);
            return parsed?.items ?? new List<MaterialMapEntry>();
        }
    }
}
