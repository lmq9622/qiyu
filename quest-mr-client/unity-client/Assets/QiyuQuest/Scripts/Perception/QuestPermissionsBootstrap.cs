using System.Collections.Generic;
using UnityEngine;

namespace Qiyu.Quest.Perception
{
    /// <summary>
    /// 启动时申请 Quest 运行时权限：Scene（MRUK）、麦克风、Passthrough Camera。
    /// 使用 Meta 官方 OVRPermissionsRequester，不自己拼 Android 权限流程。
    /// </summary>
    public class QuestPermissionsBootstrap : MonoBehaviour
    {
        [SerializeField] private bool requestScene = true;
        [SerializeField] private bool requestRecordAudio = true;
        [SerializeField] private bool requestPassthroughCamera = true;

        private void Start()
        {
            var permissions = new List<OVRPermissionsRequester.Permission>();
            if (requestScene)
            {
                permissions.Add(OVRPermissionsRequester.Permission.Scene);
            }
            if (requestRecordAudio)
            {
                permissions.Add(OVRPermissionsRequester.Permission.RecordAudio);
            }
            if (requestPassthroughCamera)
            {
                permissions.Add(OVRPermissionsRequester.Permission.PassthroughCameraAccess);
            }
            if (permissions.Count == 0)
            {
                return;
            }
            OVRPermissionsRequester.PermissionGranted += HandleGranted;
            OVRPermissionsRequester.Request(permissions);
            Debug.Log($"[QuestPermissions] 已请求 {permissions.Count} 项权限");
        }

        private static void HandleGranted(string permissionId)
        {
            Debug.Log($"[QuestPermissions] 权限已授予: {permissionId}");
        }

        private void OnDestroy()
        {
            OVRPermissionsRequester.PermissionGranted -= HandleGranted;
        }
    }
}
