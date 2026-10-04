using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.TestTools.TestRunner.Api;
using UnityEngine;

namespace Mika.Editor.Dev
{
    /// <summary>
    /// Lance les tests en mode édition et écrit le résultat dans <c>Temp/mika-tests.txt</c> — pour un outil
    /// (un agent, une CI) qui pilote l'éditeur sans fenêtre Test Runner.
    /// </summary>
    public static class TestReport
    {
        public static string ReportPath => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "Temp", "mika-tests.txt"));

        [MenuItem("Mika/Développement/Lancer les tests (mode édition)")]
        public static void RunEditMode() => Run(TestMode.EditMode, "Mika.Tests.EditMode");

        public static void Run(TestMode mode, params string[] assemblies)
        {
            if (File.Exists(ReportPath))
                File.Delete(ReportPath);
            var api = ScriptableObject.CreateInstance<TestRunnerApi>();
            api.RegisterCallbacks(new Callbacks());
            api.Execute(new ExecutionSettings(new Filter { testMode = mode, assemblyNames = assemblies }));
        }

        sealed class Callbacks : ICallbacks
        {
            public void RunStarted(ITestAdaptor tests) { }
            public void TestStarted(ITestAdaptor test) { }
            public void TestFinished(ITestResultAdaptor result) { }

            public void RunFinished(ITestResultAdaptor result)
            {
                var sb = new StringBuilder();
                sb.AppendLine($"TOTAL pass={result.PassCount} fail={result.FailCount} skip={result.SkipCount}");
                Walk(result, sb);
                File.WriteAllText(ReportPath, sb.ToString());
                Debug.Log($"[Mika] tests : {result.PassCount} réussis, {result.FailCount} échoués → {ReportPath}");
            }

            static void Walk(ITestResultAdaptor r, StringBuilder sb)
            {
                if (!r.HasChildren)
                {
                    sb.Append(r.TestStatus).Append(' ').Append(r.FullName);
                    if (r.TestStatus == TestStatus.Failed)
                        sb.Append("\n    ").Append(r.Message?.Trim().Replace("\n", "\n    "));
                    sb.AppendLine();
                    return;
                }
                foreach (var c in r.Children)
                    Walk(c, sb);
            }
        }
    }
}
