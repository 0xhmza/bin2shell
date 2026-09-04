namespace Bin2ShellUI;

static class Program
{
    [STAThread]
    static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (_, e) => ShowError(e.Exception);
        try { Application.Run(new MainForm()); }
        catch (Exception e) { ShowError(e); }
    }

    internal static void ShowError(Exception e) => MessageBox.Show(
        $"An unexpected error occurred.\n\n{e.Message}", "bin2shell",
        MessageBoxButtons.OK, MessageBoxIcon.Error);
}
