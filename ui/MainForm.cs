using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

namespace Bin2ShellUI;

public sealed class MainForm : Form
{
    [DllImport("dwmapi.dll", PreserveSig = true)]
    static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);
    const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20;

    static readonly Color BgDark = Color.FromArgb(32, 32, 32);
    static readonly Color BgControl = Color.FromArgb(45, 45, 45);
    static readonly Color BgField = Color.FromArgb(55, 55, 55);
    static readonly Color FgText = Color.FromArgb(220, 220, 220);
    static readonly Color FgDim = Color.FromArgb(160, 160, 160);
    static readonly Color AccentBlue = Color.FromArgb(0, 120, 215);
    static readonly Color BtnHover = Color.FromArgb(60, 60, 60);
    static readonly Color BorderColor = Color.FromArgb(70, 70, 70);
    static readonly Color GreenOk = Color.FromArgb(80, 200, 80);
    static readonly Color RedErr = Color.FromArgb(220, 80, 80);
    static readonly Color LogBg = Color.FromArgb(25, 25, 25);

    readonly Label _lblInput;
    readonly TextBox _txtInput;
    readonly Button _btnBrowseInput;
    readonly Label _lblEncoder;
    readonly ComboBox _cmbEncoder;
    readonly Label _lblEnvelope;
    readonly ComboBox _cmbEnvelope;
    readonly CheckBox _chkWeb;
    readonly Label _lblOutput;
    readonly TextBox _txtOutput;
    readonly Button _btnBrowseOutput;
    readonly Button _btnGenerate;
    readonly Label _lblStatus;
    readonly RichTextBox _txtLog;
    readonly Label _lblYaml;
    readonly TextBox _txtYaml;
    readonly Button _btnBrowseYaml;

    string _pythonExe = "python";
    string _scriptDir = "";

    static readonly string[] RequiredFiles = [
        "main.py",
        Path.Combine("bin2shell", "cli.py"),
        Path.Combine("bin2shell", "catalog.py"),
        Path.Combine("data", "yaml", "algos.yaml"),
    ];

    public MainForm()
    {
        SuspendLayout();

        Text = "bin2shell";
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = BgDark;
        ForeColor = FgText;
        Font = new Font("Segoe UI", 9F);
        Icon = SystemIcons.Shield;
        ClientSize = new Size(460, 520);

        var darkMode = 1;
        DwmSetWindowAttribute(Handle, DWMWA_USE_IMMERSIVE_DARK_MODE, ref darkMode, sizeof(int));

        int x = 14, w = 430, row = 14, rh = 28, gap = 6, lblGap = 22;

        // --- Input file ---
        _lblInput = MakeLabel("Input file:", x, row);
        row += lblGap;
        _txtInput = MakeTextBox(x, row, w - 80);
        _btnBrowseInput = MakeButton("...", x + w - 74, row, 74, rh);
        _btnBrowseInput.Click += BrowseInput;
        row += rh + gap + 4;

        // --- YAML catalog ---
        _lblYaml = MakeLabel("YAML catalog:", x, row);
        row += lblGap;
        _txtYaml = MakeTextBox(x, row, w - 80);
        _btnBrowseYaml = MakeButton("...", x + w - 74, row, 74, rh);
        _btnBrowseYaml.Click += BrowseYaml;
        row += rh + gap + 4;

        // --- Encoder / Envelope side by side ---
        _lblEncoder = MakeLabel("Encoder:", x, row);
        _lblEnvelope = MakeLabel("Envelope:", x + w / 2 + 4, row);
        row += lblGap;
        _cmbEncoder = MakeDarkCombo(x, row, w / 2 - 4);
        _cmbEnvelope = MakeDarkCombo(x + w / 2 + 4, row, w / 2 - 4);
        row += rh + gap + 4;

        // --- Web mode ---
        _chkWeb = new CheckBox
        {
            Text = "Web mode (emit YAML bundle with WinHTTP template)",
            Location = new Point(x, row),
            Size = new Size(w, 22),
            FlatStyle = FlatStyle.Flat,
            ForeColor = FgText,
            BackColor = BgDark,
        };
        Controls.Add(_chkWeb);
        row += 28 + gap;

        // --- Output file ---
        _lblOutput = MakeLabel("Output file:", x, row);
        row += lblGap;
        _txtOutput = MakeTextBox(x, row, w - 80);
        _btnBrowseOutput = MakeButton("...", x + w - 74, row, 74, rh);
        _btnBrowseOutput.Click += BrowseOutput;
        row += rh + gap + 8;

        // --- Generate button ---
        _btnGenerate = MakeButton("GENERATE", x, row, w, 36);
        _btnGenerate.Font = new Font("Segoe UI", 10F, FontStyle.Bold);
        _btnGenerate.BackColor = AccentBlue;
        _btnGenerate.FlatAppearance.BorderColor = AccentBlue;
        _btnGenerate.Click += Generate;
        row += 36 + gap;

        // --- Status ---
        _lblStatus = MakeLabel("Ready", x, row);
        _lblStatus.ForeColor = FgDim;
        _lblStatus.AutoSize = false;
        _lblStatus.Size = new Size(w, 18);
        row += 24;

        // --- Log ---
        int logH = ClientSize.Height - row - 10;
        _txtLog = new RichTextBox
        {
            Location = new Point(x, row),
            Size = new Size(w, logH),
            ReadOnly = true,
            BackColor = LogBg,
            ForeColor = FgDim,
            BorderStyle = BorderStyle.FixedSingle,
            Font = new Font("Consolas", 8.25F),
            WordWrap = true,
            ScrollBars = RichTextBoxScrollBars.Vertical,
        };
        Controls.Add(_txtLog);

        ResumeLayout();

        ResolvePaths();
        if (!ValidateRequiredFiles()) return;
        LoadCatalog();
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        var darkMode = 1;
        DwmSetWindowAttribute(Handle, DWMWA_USE_IMMERSIVE_DARK_MODE, ref darkMode, sizeof(int));
    }

    void ResolvePaths()
    {
        // The exe should sit alongside main.py and the bin2shell/ package
        var exeDir = Path.GetDirectoryName(Environment.ProcessPath) ?? AppContext.BaseDirectory;
        if (File.Exists(Path.Combine(exeDir, "main.py")))
        {
            _scriptDir = exeDir;
        }
        else
        {
            // Dev fallback: running from ui/bin/Debug/net8.0-windows
            var candidate = Path.GetFullPath(Path.Combine(exeDir, "..", "..", "..", ".."));
            if (File.Exists(Path.Combine(candidate, "main.py")))
                _scriptDir = candidate;
        }

        if (!string.IsNullOrEmpty(_scriptDir))
            _txtYaml.Text = Path.Combine(_scriptDir, "data", "yaml", "algos.yaml");

        foreach (var p in new[] { "python", "python3", "py" })
        {
            try
            {
                var psi = new ProcessStartInfo(p, "--version")
                {
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                using var proc = Process.Start(psi);
                proc?.WaitForExit(3000);
                if (proc?.ExitCode == 0) { _pythonExe = p; break; }
            }
            catch { }
        }
    }

    bool ValidateRequiredFiles()
    {
        var missing = new List<string>();

        if (string.IsNullOrEmpty(_scriptDir))
        {
            var exeDir = Path.GetDirectoryName(Environment.ProcessPath) ?? AppContext.BaseDirectory;
            MessageBox.Show(
                "Required script files not found.\n\n" +
                "The following files must be in the same folder as this executable:\n" +
                string.Join("\n", RequiredFiles.Select(f => "  - " + f)) +
                "\n\nLooked in: " + exeDir,
                "bin2shell - Missing Files",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            _btnGenerate.Enabled = false;
            SetStatus("Missing required files", false);
            return false;
        }

        foreach (var rel in RequiredFiles)
        {
            var full = Path.Combine(_scriptDir, rel);
            if (!File.Exists(full))
                missing.Add(rel);
        }

        if (missing.Count > 0)
        {
            MessageBox.Show(
                "Some required files are missing:\n\n" +
                string.Join("\n", missing.Select(f => "  - " + f)) +
                "\n\nThey should be in the same folder as this executable:\n" +
                _scriptDir,
                "bin2shell - Missing Files",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            _btnGenerate.Enabled = false;
            SetStatus("Missing required files", false);
            return false;
        }

        return true;
    }

    void LoadCatalog()
    {
        _cmbEncoder.Items.Clear();
        _cmbEnvelope.Items.Clear();

        var yamlPath = _txtYaml.Text.Trim();
        if (string.IsNullOrEmpty(yamlPath) || !File.Exists(yamlPath))
        {
            _cmbEncoder.Items.Add("[0] none");
            _cmbEnvelope.Items.Add("[0] none");
            _cmbEncoder.SelectedIndex = 0;
            _cmbEnvelope.SelectedIndex = 0;
            return;
        }

        try
        {
            var script = $@"
import json, sys, yaml
with open(r'{yamlPath.Replace("'", "\\'")}', 'r') as f:
    d = yaml.safe_load(f)
out = {{'encoders': [], 'envelopes': []}}
for e in d.get('encoders', []):
    out['encoders'].append({{'index': e['index'], 'name': e.get('name','')}})
for e in d.get('envelopes', []):
    out['envelopes'].append({{'index': e['index'], 'name': e.get('name','')}})
print(json.dumps(out))
";
            var psi = new ProcessStartInfo(_pythonExe, "-c \"" + script.Replace("\"", "\\\"") + "\"")
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = _scriptDir,
            };
            using var proc = Process.Start(psi);
            var stdout = proc?.StandardOutput.ReadToEnd() ?? "";
            proc?.WaitForExit(5000);

            if (!string.IsNullOrWhiteSpace(stdout))
            {
                using var doc = JsonDocument.Parse(stdout.Trim());
                var root = doc.RootElement;
                foreach (var enc in root.GetProperty("encoders").EnumerateArray())
                    _cmbEncoder.Items.Add($"[{enc.GetProperty("index").GetInt32()}] {enc.GetProperty("name").GetString()}");
                foreach (var env in root.GetProperty("envelopes").EnumerateArray())
                    _cmbEnvelope.Items.Add($"[{env.GetProperty("index").GetInt32()}] {env.GetProperty("name").GetString()}");
            }
        }
        catch
        {
            _cmbEncoder.Items.Add("[0] none");
            _cmbEnvelope.Items.Add("[0] none");
        }

        if (_cmbEncoder.Items.Count > 0) _cmbEncoder.SelectedIndex = 0;
        if (_cmbEnvelope.Items.Count > 0) _cmbEnvelope.SelectedIndex = 0;
    }

    int ExtractIndex(ComboBox cmb)
    {
        var text = cmb.SelectedItem?.ToString() ?? "[0]";
        var start = text.IndexOf('[') + 1;
        var end = text.IndexOf(']');
        if (start > 0 && end > start && int.TryParse(text[start..end], out var idx))
            return idx;
        return 0;
    }

    async void Generate(object? sender, EventArgs e)
    {
        var inputPath = _txtInput.Text.Trim();
        if (string.IsNullOrEmpty(inputPath) || !File.Exists(inputPath))
        { SetStatus("Input file not found", false); return; }

        var outputPath = _txtOutput.Text.Trim();
        if (string.IsNullOrEmpty(outputPath))
        { SetStatus("No output file specified", false); return; }

        var mainPy = Path.Combine(_scriptDir, "main.py");
        if (!File.Exists(mainPy))
        { SetStatus("main.py not found", false); return; }

        var encIdx = ExtractIndex(_cmbEncoder);
        var envIdx = ExtractIndex(_cmbEnvelope);

        var args = new List<string>();
        if (encIdx > 0 || envIdx > 0)
        {
            args.AddRange(["-e", encIdx.ToString()]);
            args.AddRange(["-v", envIdx.ToString()]);
        }
        var yamlPath = _txtYaml.Text.Trim();
        if (!string.IsNullOrEmpty(yamlPath) && File.Exists(yamlPath))
            args.AddRange(["-y", yamlPath]);
        if (_chkWeb.Checked) args.Add("-w");
        args.AddRange(["-o", outputPath]);
        args.Add(inputPath);

        var outDir = Path.GetDirectoryName(outputPath);
        if (!string.IsNullOrEmpty(outDir) && !Directory.Exists(outDir))
            Directory.CreateDirectory(outDir);

        _btnGenerate.Enabled = false;
        SetStatus("Generating...", true);
        _txtLog.Clear();

        try
        {
            var argStr = string.Join(" ", args.Select(a => a.Contains(' ') ? $"\"{a}\"" : a));
            Log($"> {_pythonExe} main.py {argStr}");

            var psi = new ProcessStartInfo
            {
                FileName = _pythonExe,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = _scriptDir,
            };
            psi.ArgumentList.Add(mainPy);
            foreach (var a in args) psi.ArgumentList.Add(a);

            using var proc = new Process { StartInfo = psi };
            var sbOut = new StringBuilder();
            var sbErr = new StringBuilder();
            proc.OutputDataReceived += (_, d) => { if (d.Data != null) sbOut.AppendLine(d.Data); };
            proc.ErrorDataReceived += (_, d) => { if (d.Data != null) sbErr.AppendLine(d.Data); };

            proc.Start();
            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
            await proc.WaitForExitAsync();

            if (!string.IsNullOrWhiteSpace(sbErr.ToString())) Log(sbErr.ToString().TrimEnd());
            if (!string.IsNullOrWhiteSpace(sbOut.ToString())) Log(sbOut.ToString().TrimEnd());

            if (proc.ExitCode == 0)
            {
                var fi = new FileInfo(outputPath);
                SetStatus($"Done \u2014 {fi.Length:N0} bytes written to {fi.Name}", true);
                Log($"Output: {outputPath}");
            }
            else
                SetStatus($"Error (exit code {proc.ExitCode})", false);
        }
        catch (Exception ex)
        {
            SetStatus("Error: " + ex.Message, false);
            Log(ex.ToString());
        }
        finally { _btnGenerate.Enabled = true; }
    }

    string DefaultOutputPath(string inputPath)
    {
        var dir = Path.Combine(_scriptDir, "output_snippets");
        var name = Path.GetFileName(inputPath);
        var ts = DateTime.Now.ToString("yyyyMMdd_HHmmss");
        return Path.Combine(dir, $"{name}_{ts}.cpp_snippet");
    }

    void BrowseInput(object? s, EventArgs e)
    {
        using var dlg = new OpenFileDialog
        {
            Title = "Select input binary",
            Filter = "Binary files (*.bin)|*.bin|All files (*.*)|*.*",
        };
        if (dlg.ShowDialog() == DialogResult.OK)
        {
            _txtInput.Text = dlg.FileName;
            _txtOutput.Text = DefaultOutputPath(dlg.FileName);
        }
    }

    void BrowseOutput(object? s, EventArgs e)
    {
        using var dlg = new SaveFileDialog
        {
            Title = "Save output",
            Filter = "C++ files (*.cpp)|*.cpp|YAML files (*.yaml)|*.yaml|All files (*.*)|*.*",
        };
        if (dlg.ShowDialog() == DialogResult.OK)
            _txtOutput.Text = dlg.FileName;
    }

    void BrowseYaml(object? s, EventArgs e)
    {
        using var dlg = new OpenFileDialog
        {
            Title = "Select algorithms YAML",
            Filter = "YAML files (*.yaml;*.yml)|*.yaml;*.yml|All files (*.*)|*.*",
        };
        if (dlg.ShowDialog() == DialogResult.OK)
        {
            _txtYaml.Text = dlg.FileName;
            LoadCatalog();
        }
    }

    void SetStatus(string msg, bool ok)
    {
        _lblStatus.Text = msg;
        _lblStatus.ForeColor = ok ? GreenOk : RedErr;
    }

    void Log(string msg)
    {
        _txtLog.AppendText(msg + Environment.NewLine);
    }

    // --- Factory helpers ---

    Label MakeLabel(string text, int x, int y)
    {
        var lbl = new Label
        {
            Text = text,
            Location = new Point(x, y),
            AutoSize = true,
            ForeColor = FgDim,
            BackColor = BgDark,
        };
        Controls.Add(lbl);
        return lbl;
    }

    TextBox MakeTextBox(int x, int y, int w)
    {
        var tb = new TextBox
        {
            Location = new Point(x, y),
            Size = new Size(w, 28),
            BackColor = BgField,
            ForeColor = FgText,
            BorderStyle = BorderStyle.FixedSingle,
        };
        Controls.Add(tb);
        return tb;
    }

    Button MakeButton(string text, int x, int y, int w, int h)
    {
        var btn = new Button
        {
            Text = text,
            Location = new Point(x, y),
            Size = new Size(w, h),
            FlatStyle = FlatStyle.Flat,
            BackColor = BgControl,
            ForeColor = FgText,
            Cursor = Cursors.Hand,
        };
        btn.FlatAppearance.BorderColor = BorderColor;
        btn.FlatAppearance.MouseOverBackColor = BtnHover;
        Controls.Add(btn);
        return btn;
    }

    ComboBox MakeDarkCombo(int x, int y, int w)
    {
        var cmb = new ComboBox
        {
            Location = new Point(x, y),
            Size = new Size(w, 28),
            DropDownStyle = ComboBoxStyle.DropDownList,
            DrawMode = DrawMode.OwnerDrawFixed,
            ItemHeight = 22,
            BackColor = BgField,
            ForeColor = FgText,
            FlatStyle = FlatStyle.Flat,
        };
        cmb.DrawItem += (s, e) =>
        {
            if (e.Index < 0) return;
            var bg = (e.State & DrawItemState.Selected) != 0 ? AccentBlue : BgField;
            using var bgBrush = new SolidBrush(bg);
            using var fgBrush = new SolidBrush(FgText);
            e.Graphics.FillRectangle(bgBrush, e.Bounds);
            var text = cmb.Items[e.Index]?.ToString() ?? "";
            e.Graphics.DrawString(text, cmb.Font, fgBrush,
                new RectangleF(e.Bounds.X + 4, e.Bounds.Y + 2, e.Bounds.Width - 8, e.Bounds.Height));
        };
        Controls.Add(cmb);
        return cmb;
    }
}
