using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("Maagal Karaoke Studio")]
[assembly: AssemblyProduct("Maagal Karaoke Studio")]
[assembly: AssemblyCompany("Maagal Hebrew")]

internal static class WindowsLauncher
{
    [STAThread]
    private static int Main(string[] args)
    {
        string resources = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Studio");
        try
        {
            string python = Path.Combine(resources, "python", "python.exe");
            string script = Path.Combine(resources, "launch.py");
            var start = new ProcessStartInfo(python, "-I -B \"" + script + "\"")
            {
                WorkingDirectory = resources,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            using (var process = Process.Start(start))
            {
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch (Exception)
        {
            MessageBox.Show("Maagal Karaoke Studio could not open. Run its installer again to repair the application.",
                "Maagal Karaoke Studio", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
