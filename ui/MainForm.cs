using System.Diagnostics;
using System.Text.RegularExpressions;

namespace Bin2ShellUI;

public sealed class MainForm : Form
{
    readonly TextBox input = new() { Dock = DockStyle.Fill };
    readonly TextBox yaml = new() { Dock = DockStyle.Fill };
    readonly TextBox output = new() { Dock = DockStyle.Fill };
    readonly ComboBox encoder = ListBox(), envelope = ListBox(), helper = ListBox(), carrier = ListBox();
    readonly RadioButton inline = new() { Text = "Inline", AutoSize = true, Checked = true };
    readonly RadioButton web = new() { Text = "Web fetch", AutoSize = true };
    readonly RadioButton file = new() { Text = "Carrier file", AutoSize = true };
    readonly Label helperLabel = Label("Web helper"), carrierLabel = Label("Carrier format");
    readonly Button generate = new() { Text = "Generate", AutoSize = true, MinimumSize = new Size(96, 30) };
    readonly Label status = new() { AutoSize = true, Anchor = AnchorStyles.Left };
    readonly TextBox log = new()
    {
        Dock = DockStyle.Fill,
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Both,
        WordWrap = false,
        Font = new Font(FontFamily.GenericMonospace, 9),
    };
    readonly ErrorProvider errors = new() { BlinkStyle = ErrorBlinkStyle.NeverBlink };

    string root = "", python = "", loadedYaml = "";
    bool catalogValid;

    public MainForm()
    {
        Text = "bin2shell";
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        ClientSize = new Size(680, 570);
        Font = new Font("Segoe UI", 9);
        AutoScaleMode = AutoScaleMode.Dpi;
        errors.ContainerControl = this;

        var page = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(12), RowCount = 5 };
        page.RowStyles.Add(new RowStyle(SizeType.Absolute, 124));
        page.RowStyles.Add(new RowStyle(SizeType.Absolute, 66));
        page.RowStyles.Add(new RowStyle(SizeType.Absolute, 130));
        page.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        page.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
        Controls.Add(page);

        page.Controls.Add(FilesGroup(), 0, 0);
        page.Controls.Add(EncodingGroup(), 0, 1);
        page.Controls.Add(SourceGroup(), 0, 2);

        var outputLog = new GroupBox { Text = "Output log", Dock = DockStyle.Fill, Padding = new Padding(8) };
        outputLog.Controls.Add(log);
        page.Controls.Add(outputLog, 0, 3);

        var actions = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2 };
        actions.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        actions.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        actions.Controls.Add(status, 0, 0);
        actions.Controls.Add(generate, 1, 0);
        page.Controls.Add(actions, 0, 4);
        AcceptButton = generate;

        carrier.Items.AddRange(["ini", "png", "bmp", "ico"]);
        carrier.SelectedIndex = 0;
        generate.Click += Generate;
        inline.CheckedChanged += (_, _) => SourceChanged();
        web.CheckedChanged += (_, _) => SourceChanged();
        file.CheckedChanged += (_, _) => SourceChanged();
        input.TextChanged += (_, _) => ValidateInputs(false);
        yaml.TextChanged += (_, _) => ValidateInputs(false);
        output.TextChanged += (_, _) => ValidateInputs(false);
        yaml.Validated += (_, _) => LoadCatalog();
        encoder.SelectedIndexChanged += (_, _) => ValidateInputs(false);
        envelope.SelectedIndexChanged += (_, _) => ValidateInputs(false);
        helper.SelectedIndexChanged += (_, _) => ValidateInputs(false);
        carrier.SelectedIndexChanged += (_, _) => ValidateInputs(false);

        root = FindRoot();
        python = FindPython();
        if (root.Length > 0) yaml.Text = Path.Combine(root, "data", "yaml", "algos.yaml");
        if (root.Length > 0 && python.Length > 0) LoadCatalog();
        SourceChanged();
    }

    GroupBox FilesGroup()
    {
        var group = new GroupBox { Text = "Files", Dock = DockStyle.Fill };
        var grid = Grid(3, 3);
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 86));
        AddFileRow(grid, 0, "Input", input, BrowseInput);
        AddFileRow(grid, 1, "Playbook", yaml, BrowseYaml);
        AddFileRow(grid, 2, "Output", output, BrowseOutput);
        group.Controls.Add(grid);
        return group;
    }

    GroupBox EncodingGroup()
    {
        var group = new GroupBox { Text = "Encoding", Dock = DockStyle.Fill };
        var grid = Grid(4, 1);
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        grid.Controls.Add(Label("Encoder"), 0, 0);
        grid.Controls.Add(encoder, 1, 0);
        grid.Controls.Add(Label("Envelope"), 2, 0);
        grid.Controls.Add(envelope, 3, 0);
        group.Controls.Add(grid);
        return group;
    }

    GroupBox SourceGroup()
    {
        var group = new GroupBox { Text = "Payload source", Dock = DockStyle.Fill };
        var grid = Grid(2, 3);
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        var modes = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, WrapContents = false };
        modes.Controls.AddRange([inline, web, file]);
        grid.Controls.Add(modes, 0, 0);
        grid.SetColumnSpan(modes, 2);
        grid.Controls.Add(helperLabel, 0, 1);
        grid.Controls.Add(helper, 1, 1);
        grid.Controls.Add(carrierLabel, 0, 2);
        grid.Controls.Add(carrier, 1, 2);
        group.Controls.Add(grid);
        return group;
    }

    static TableLayoutPanel Grid(int columns, int rows) => new()
    {
        Dock = DockStyle.Fill,
        ColumnCount = columns,
        RowCount = rows,
        Padding = new Padding(6),
    };

    static Label Label(string text) => new() { Text = text, AutoSize = true, Anchor = AnchorStyles.Left };

    static ComboBox ListBox() => new()
    {
        Dock = DockStyle.Fill,
        DropDownStyle = ComboBoxStyle.DropDownList,
        IntegralHeight = false,
        DropDownHeight = 240,
    };

    static void AddFileRow(TableLayoutPanel grid, int row, string name, TextBox box, EventHandler click)
    {
        var button = new Button { Text = "Browse...", Dock = DockStyle.Fill };
        button.Click += click;
        grid.Controls.Add(Label(name), 0, row);
        grid.Controls.Add(box, 1, row);
        grid.Controls.Add(button, 2, row);
    }

    void SourceChanged()
    {
        helper.Enabled = web.Checked;
        helperLabel.Enabled = web.Checked;
        carrier.Enabled = file.Checked;
        carrierLabel.Enabled = file.Checked;
        ValidateInputs(false);
    }

    string FindRoot()
    {
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir is not null; dir = dir.Parent)
            if (File.Exists(Path.Combine(dir.FullName, "main.py")) &&
                File.Exists(Path.Combine(dir.FullName, "bin2shell", "cli.py"))) return dir.FullName;
        return "";
    }

    static string FindPython()
    {
        foreach (var name in new[] { "python", "py" })
            try
            {
                using var process = Process.Start(new ProcessStartInfo(name, "--version")
                { UseShellExecute = false, CreateNoWindow = true });
                if (process is not null && process.WaitForExit(2000) && process.ExitCode == 0) return name;
                if (process is { HasExited: false }) process.Kill(true);
            }
            catch { }
        return "";
    }

    void LoadCatalog()
    {
        catalogValid = false;
        loadedYaml = "";
        encoder.Items.Clear();
        envelope.Items.Clear();
        helper.Items.Clear();
        try
        {
            if (!File.Exists(yaml.Text) || python.Length == 0 || root.Length == 0) return;
            var start = StartInfo();
            start.ArgumentList.Add(Path.Combine(root, "main.py"));
            start.ArgumentList.Add("-y");
            start.ArgumentList.Add(yaml.Text);
            start.ArgumentList.Add("--help");
            using var process = Process.Start(start) ?? throw new InvalidOperationException("Could not start Python.");
            var stdout = process.StandardOutput.ReadToEndAsync();
            var stderr = process.StandardError.ReadToEndAsync();
            if (!process.WaitForExit(5000)) { process.Kill(true); throw new TimeoutException("Loading the playbook timed out."); }
            var text = stdout.GetAwaiter().GetResult();
            _ = stderr.GetAwaiter().GetResult();

            ComboBox? target = null;
            foreach (var line in text.Split('\n'))
            {
                if (line.StartsWith("available "))
                    target = line.Contains("encoders:") ? encoder
                        : line.Contains("envelopes:") ? envelope
                        : line.Contains("web helpers:") ? helper : null;
                var match = Regex.Match(line, @"^\s+\[(\d+)]\s+(\S+)");
                if (target is not null && match.Success)
                    target.Items.Add($"[{match.Groups[1].Value}] {match.Groups[2].Value}");
            }
            catalogValid = process.ExitCode == 0 && encoder.Items.Count > 0 &&
                envelope.Items.Count > 0 && helper.Items.Count > 0;
            if (catalogValid) loadedYaml = Path.GetFullPath(yaml.Text);
        }
        catch (Exception e) { log.Text = e.Message; }
        finally
        {
            SelectFirst(encoder, "[0] passthrough");
            SelectFirst(envelope, "[0] bare_bytes");
            SelectFirst(helper, "[0] winhttp");
            ValidateInputs(false);
        }
    }

    static void SelectFirst(ComboBox box, string fallback)
    {
        if (box.Items.Count == 0) box.Items.Add(fallback);
        box.SelectedIndex = 0;
    }

    ProcessStartInfo StartInfo() => new()
    {
        FileName = python,
        WorkingDirectory = root,
        UseShellExecute = false,
        CreateNoWindow = true,
        RedirectStandardOutput = true,
        RedirectStandardError = true,
    };

    bool ValidateInputs(bool showErrors)
    {
        errors.Clear();
        string message;
        Control? bad = null;
        if (root.Length == 0) message = "Application files were not found.";
        else if (python.Length == 0) message = "Python was not found.";
        else if (input.TextLength == 0) { message = "Select an input file."; bad = input; }
        else if (!File.Exists(input.Text)) { message = "The input file does not exist."; bad = input; }
        else if (yaml.TextLength == 0) { message = "Select a playbook."; bad = yaml; }
        else if (!File.Exists(yaml.Text)) { message = "The playbook does not exist."; bad = yaml; }
        else if (!SamePath(yaml.Text, loadedYaml) || !catalogValid)
        { message = "The playbook could not be loaded."; bad = yaml; }
        else if (encoder.SelectedIndex < 0 || envelope.SelectedIndex < 0)
            message = "Select an encoder and envelope.";
        else if (web.Checked && helper.SelectedIndex < 0) message = "Select a web helper.";
        else if (file.Checked && carrier.SelectedIndex < 0) message = "Select a carrier format.";
        else if (output.TextLength == 0) { message = "Choose an output file."; bad = output; }
        else if (!ValidPath(output.Text)) { message = "The output path is invalid."; bad = output; }
        else if (SamePath(input.Text, output.Text)) { message = "Input and output must be different files."; bad = output; }
        else { status.Text = "Ready"; generate.Enabled = true; return true; }

        status.Text = message;
        generate.Enabled = false;
        if (showErrors && bad is not null) errors.SetError(bad, message);
        return false;
    }

    static bool ValidPath(string path)
    {
        try { return Path.GetFileName(Path.GetFullPath(path)).Length > 0; }
        catch { return false; }
    }

    static bool SamePath(string a, string b)
    {
        if (a.Length == 0 || b.Length == 0) return false;
        try { return string.Equals(Path.GetFullPath(a), Path.GetFullPath(b), StringComparison.OrdinalIgnoreCase); }
        catch { return false; }
    }

    static int IndexOf(ComboBox box)
    {
        var end = box.Text.IndexOf(']');
        return end > 1 && int.TryParse(box.Text[1..end], out var index) ? index : 0;
    }

    void BrowseInput(object? sender, EventArgs e) => Safe(() =>
    {
        using var dialog = new OpenFileDialog { Filter = "Binary files (*.bin)|*.bin|All files (*.*)|*.*" };
        if (dialog.ShowDialog() != DialogResult.OK) return;
        input.Text = dialog.FileName;
        output.Text = Path.Combine(root, "output_snippets",
            $"{Path.GetFileNameWithoutExtension(dialog.FileName)}_{DateTime.Now:yyyyMMdd_HHmmss}.cpp");
    });

    void BrowseYaml(object? sender, EventArgs e) => Safe(() =>
    {
        using var dialog = new OpenFileDialog { Filter = "YAML files (*.yaml;*.yml)|*.yaml;*.yml|All files (*.*)|*.*" };
        if (dialog.ShowDialog() == DialogResult.OK) { yaml.Text = dialog.FileName; LoadCatalog(); }
    });

    void BrowseOutput(object? sender, EventArgs e) => Safe(() =>
    {
        using var dialog = new SaveFileDialog { Filter = "C++ files (*.cpp)|*.cpp|All files (*.*)|*.*" };
        if (dialog.ShowDialog() == DialogResult.OK) output.Text = dialog.FileName;
    });

    async void Generate(object? sender, EventArgs e)
    {
        if (!ValidateInputs(true)) return;
        generate.Enabled = false;
        status.Text = "Generating...";
        log.Clear();
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output.Text))!);
            var start = StartInfo();
            foreach (var arg in Arguments()) start.ArgumentList.Add(arg);
            using var process = Process.Start(start) ?? throw new InvalidOperationException("Could not start Python.");
            var stdout = process.StandardOutput.ReadToEndAsync();
            var stderr = process.StandardError.ReadToEndAsync();
            await process.WaitForExitAsync();
            var result = ((await stdout) + (await stderr)).Trim();
            if (IsDisposed) return;
            log.Text = result;
            status.Text = process.ExitCode == 0 && File.Exists(output.Text)
                ? $"Created {Path.GetFileName(output.Text)}"
                : $"Generation failed (exit code {process.ExitCode}).";
        }
        catch (Exception ex) { if (!IsDisposed) Report(ex); }
        finally { if (!IsDisposed) generate.Enabled = true; }
    }

    IEnumerable<string> Arguments()
    {
        yield return Path.Combine(root, "main.py");
        yield return "-e"; yield return IndexOf(encoder).ToString();
        yield return "-v"; yield return IndexOf(envelope).ToString();
        yield return "-y"; yield return yaml.Text;
        if (web.Checked) { yield return "-w"; yield return "-wh"; yield return IndexOf(helper).ToString(); }
        if (file.Checked) { yield return "--carrier"; yield return carrier.Text; }
        yield return "-o"; yield return output.Text;
        yield return input.Text;
    }

    void Safe(Action action) { try { action(); } catch (Exception e) { Report(e); } }
    void Report(Exception e) { status.Text = e.Message; log.Text = e.ToString(); }
}
