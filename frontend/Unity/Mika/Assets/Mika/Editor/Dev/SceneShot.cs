using System.IO;
using UnityEngine;
using UnityEngine.Rendering.Universal;

namespace Mika.Editor.Dev
{
    /// <summary>
    /// Une photo de la scène ouverte, depuis un point et une direction, rendue avec le post-traitement — pour
    /// vérifier un rendu sans ouvrir de fenêtre (un outil, un agent). Écrite dans <c>Temp/</c>.
    /// </summary>
    public static class SceneShot
    {
        public static string Capture(Vector3 position, Vector3 lookAt, string name = "capture", int width = 1280, int height = 720, float fov = 70f)
        {
            var go = new GameObject("__SceneShot") { hideFlags = HideFlags.HideAndDontSave };
            try
            {
                var cam = go.AddComponent<Camera>();
                cam.fieldOfView = fov;
                cam.nearClipPlane = 0.03f;
                var urp = go.AddComponent<UniversalAdditionalCameraData>();
                urp.renderPostProcessing = true;
                urp.antialiasing = AntialiasingMode.SubpixelMorphologicalAntiAliasing;
                go.transform.position = position;
                go.transform.rotation = Quaternion.LookRotation(lookAt - position, Vector3.up);
                var rt = RenderTexture.GetTemporary(width, height, 24, RenderTextureFormat.ARGB32);
                cam.targetTexture = rt;
                cam.Render();
                var previous = RenderTexture.active;
                RenderTexture.active = rt;
                var tex = new Texture2D(width, height, TextureFormat.RGB24, false);
                tex.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                tex.Apply();
                RenderTexture.active = previous;
                cam.targetTexture = null;
                RenderTexture.ReleaseTemporary(rt);
                var path = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "Temp", name + ".png"));
                File.WriteAllBytes(path, tex.EncodeToPNG());
                Object.DestroyImmediate(tex);
                return path;
            }
            finally
            {
                Object.DestroyImmediate(go);
            }
        }
    }
}
