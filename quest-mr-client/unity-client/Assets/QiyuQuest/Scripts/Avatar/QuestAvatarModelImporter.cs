using System;
using System.IO;
using System.Threading.Tasks;
using Qiyu.Quest.UI;
using UnityEngine;
using UnityEngine.Networking;

namespace Qiyu.Quest.Avatar
{
    /// <summary>
    /// 角色模型导入（VRM / GLB）。
    ///
    /// 当前已实现：
    /// - 本地 StreamingAssets 路径检查；
    /// - http(s) URL 下载到 persistentDataPath（真实下载，不假装成功）；
    /// - 导入器探测：UniVRM / glTFast 未安装时如实报错，不伪造模型。
    ///
    /// 预留接口：安装 UniVRM（VRM 1.0/0.x）或 glTFast（GLB）后，
    /// 在 LoadWithInstalledImporter 中接入即可，UI 无需改动。
    /// </summary>
    public class QuestAvatarModelImporter : MonoBehaviour
    {
        [SerializeField] private Transform avatarRoot;
        [SerializeField] private string fallbackFileName = "avatar.vrm";

        public bool IsModelLoaded { get; private set; }
        public string CurrentModelName { get; private set; } = "";
        public string LastError { get; private set; } = "";
        public GameObject CurrentModel { get; private set; }
        public event Action<GameObject> OnModelLoaded;
        public event Action<string> OnImportFailed;

        public async void ImportFromConfiguredSource()
        {
            var source = QiyuSettings.AvatarUrl;
            if (string.IsNullOrWhiteSpace(source))
            {
                Fail("请先填写模型地址（URL 或 StreamingAssets 文件名）");
                return;
            }
            try
            {
                string localPath;
                if (source.StartsWith("http://") || source.StartsWith("https://"))
                {
                    localPath = await DownloadAsync(source);
                }
                else
                {
                    localPath = Path.Combine(Application.streamingAssetsPath, source);
                    if (!File.Exists(localPath))
                    {
                        Fail($"本地模型不存在：{localPath}");
                        return;
                    }
                }
                LoadWithInstalledImporter(localPath);
            }
            catch (Exception e)
            {
                Fail($"导入失败：{e.Message}");
            }
        }

        public void RemoveModel()
        {
            if (CurrentModel != null)
            {
                Destroy(CurrentModel);
            }
            CurrentModel = null;
            IsModelLoaded = false;
            CurrentModelName = "";
            LastError = "";
        }

        private async Task<string> DownloadAsync(string url)
        {
            var fileName = string.IsNullOrWhiteSpace(fallbackFileName)
                ? "avatar.vrm" : fallbackFileName;
            var extension = Path.GetExtension(new Uri(url).AbsolutePath);
            if (!string.IsNullOrEmpty(extension))
            {
                fileName = "avatar" + extension;
            }
            var target = Path.Combine(Application.persistentDataPath, fileName);
            using var request = UnityWebRequest.Get(url);
            var operation = request.SendWebRequest();
            while (!operation.isDone)
            {
                await Task.Yield();
            }
            if (request.result != UnityWebRequest.Result.Success)
            {
                throw new IOException($"下载失败 {request.responseCode}: {request.error}");
            }
            await File.WriteAllBytesAsync(target, request.downloadHandler.data);
            Debug.Log($"[QuestAvatar] 已下载模型 {target} ({request.downloadHandler.data.Length} bytes)");
            return target;
        }

        private void LoadWithInstalledImporter(string localPath)
        {
            var extension = Path.GetExtension(localPath).ToLowerInvariant();
            // UniVRM / glTFast 都是可选依赖；未安装时如实报错。
            var vrmType = Type.GetType("UniVRM10.Vrm10Importer, VRM10")
                          ?? Type.GetType("VRM.VRMImporterContext, VRM");
            var gltfType = Type.GetType("GLTFast.GltfImport, glTFast");
            if (extension == ".vrm" && vrmType == null)
            {
                Fail("检测到 VRM 文件，但工程未安装 UniVRM。请安装 com.vrm.vrm 后再导入。");
                return;
            }
            if ((extension == ".glb" || extension == ".gltf") && gltfType == null)
            {
                Fail("检测到 GLB/GLTF 文件，但工程未安装 glTFast。请安装 com.unity.cloud.gltfast 后再导入。");
                return;
            }
            // 预留：安装导入器后在此处加载，并把结果挂到 avatarRoot。
            Fail($"模型已下载到 {localPath}，但当前导入器接口尚未接入（预留）。");
        }

        private void Fail(string message)
        {
            LastError = message;
            IsModelLoaded = false;
            Debug.LogWarning($"[QuestAvatar] {message}");
            OnImportFailed?.Invoke(message);
        }
    }
}
