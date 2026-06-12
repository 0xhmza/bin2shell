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

    // VS Code–inspired dark palette
    static readonly Color BgDark     = Color.FromArgb(30, 30, 30);
    static readonly Color BgField    = Color.FromArgb(58, 58, 58);
    static readonly Color BgButton   = Color.FromArgb(44, 44, 44);
    static readonly Color FgText     = Color.FromArgb(212, 212, 212);
    static readonly Color FgDim      = Color.FromArgb(118, 118, 118);
    static readonly Color FgSection  = Color.FromArgb(86, 156, 214);
    static readonly Color AccentBlue = Color.FromArgb(0, 122, 204);
    static readonly Color AccentHov  = Color.FromArgb(28, 143, 220);
    static readonly Color BtnHover   = Color.FromArgb(62, 62, 62);
    static readonly Color BorderColor = Color.FromArgb(65, 65, 65);
    static readonly Color GreenOk    = Color.FromArgb(78, 201, 176);
    static readonly Color RedErr     = Color.FromArgb(244, 135, 113);
    static readonly Color LogBg      = Color.FromArgb(20, 20, 20);
    static readonly Color SepColor   = Color.FromArgb(50, 50, 50);

    const int PadX  = 16;
    const int FormW = 580;

    readonly Label       _lblInput;
    readonly TextBox     _txtInput;
    readonly Button      _btnBrowseInput;
    readonly Label       _lblEncoder;
    readonly ComboBox    _cmbEncoder;
    readonly Label       _lblEnvelope;
    readonly ComboBox    _cmbEnvelope;
    readonly CheckBox    _chkWeb;
    readonly Label       _lblWebHelper;
    readonly ComboBox    _cmbWebHelper;
    readonly Label       _lblOutput;
    readonly TextBox     _txtOutput;
    readonly Button      _btnBrowseOutput;
    readonly Button      _btnCopyOutput;
    readonly Button      _btnGenerate;
    readonly Label       _lblStatus;
    readonly RichTextBox _txtLog;
    readonly Button      _btnClearLog;
    readonly Label       _lblYaml;
    readonly TextBox     _txtYaml;
    readonly Button      _btnBrowseYaml;
    readonly Label       _lblCarrier;
    readonly ComboBox    _cmbCarrier;
    readonly ToolTip     _tip;

    static readonly string[] CarrierNames = ["(none)", "ini", "png", "bmp", "ico"];

    string _pythonExe = "python";
    string _scriptDir = "";

    static readonly string[] RequiredFiles = [
        "main.py",
        Path.Combine("bin2shell", "cli.py"),
        Path.Combine("bin2shell", "playbook.py"),
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
        ClientSize = new Size(FormW, 748);

        int W = FormW - PadX * 2;   // usable inner width
        _tip = new ToolTip { AutoPopDelay = 7000, InitialDelay = 500, ReshowDelay = 200 };

        const int Rh = 26, Gap = 6;
        int y = 14;

        // ── Input file ────────────────────────────────────────────────
        SectionHeader("Input file", ref y, W);
        _lblInput = MakeLabel("Payload binary:", PadX, y); y += 20;
        _txtInput = MakeTextBox(PadX, y, W - 86);
        _btnBrowseInput = MakeButton("Browse…", PadX + W - 80, y, 80, Rh);
        _btnBrowseInput.Click += BrowseInput;
        _tip.SetToolTip(_txtInput,       "Path to the binary shellcode file to embed.");
        _tip.SetToolTip(_btnBrowseInput, "Open a file browser.");
        y += Rh + Gap + 8;

        // ── YAML playbook ─────────────────────────────────────────────
        SectionHeader("YAML playbook", ref y, W);
        _lblYaml = MakeLabel("Algorithms playbook:", PadX, y); y += 20;
        _txtYaml = MakeTextBox(PadX, y, W - 86);
        _btnBrowseYaml = MakeButton("Browse…", PadX + W - 80, y, 80, Rh);
        _btnBrowseYaml.Click += BrowseYaml;
        _tip.SetToolTip(_txtYaml,       "Path to algos.yaml — defines encoders, envelopes and web helpers.");
        _tip.SetToolTip(_btnBrowseYaml, "Browse for the YAML playbook.");
        y += Rh + Gap + 8;

        // ── Encoding ──────────────────────────────────────────────────
        SectionHeader("Encoding", ref y, W);
        int half = (W - 8) / 2;
        _lblEncoder  = MakeLabel("Encoder:",  PadX,            y);
        _lblEnvelope = MakeLabel("Envelope:", PadX + half + 8, y);
        y += 20;
        _cmbEncoder  = MakeDarkCombo(PadX,            y, half);
        _cmbEnvelope = MakeDarkCombo(PadX + half + 8, y, half);
        _tip.SetToolTip(_cmbEncoder,  "Encoding algorithm applied to the raw payload bytes.");
        _tip.SetToolTip(_cmbEnvelope, "Wrapping layer placed around the encoded bytes.");
        y += Rh + Gap;

        _chkWeb = new CheckBox
        {
            Text = "Web mode — fetch payload at runtime via WinHTTP",
            Location = new Point(PadX, y),
            Size = new Size(W, 22),
            FlatStyle = FlatStyle.Flat,
            ForeColor = FgText,
            BackColor = BgDark,
        };
        _chkWeb.CheckedChanged += WebModeToggled;
        _tip.SetToolTip(_chkWeb, "Emits a WinHTTP fetch stub instead of inlining the payload bytes.");
        Controls.Add(_chkWeb);
        y += 26 + Gap;

        // Always visible; enabled only when web mode is on
        _lblWebHelper = MakeLabel("Web helper:", PadX, y);
        _lblWebHelper.Enabled = false;
        y += 20;
        _cmbWebHelper = MakeDarkCombo(PadX, y, W);
        _cmbWebHelper.Enabled = false;
        _tip.SetToolTip(_lblWebHelper, "HTTP fetch helper template (enable web mode to use).");
        _tip.SetToolTip(_cmbWebHelper, "HTTP fetch helper template to include in the generated stub.");
        y += Rh + Gap + 8;

        // ── Carrier ───────────────────────────────────────────────────
        SectionHeader("Carrier", ref y, W);
        _lblCarrier = MakeLabel("Decoy file format:", PadX, y); y += 20;
        _cmbCarrier = MakeDarkCombo(PadX, y, W);
        foreach (var n in CarrierNames) _cmbCarrier.Items.Add(n);
        _cmbCarrier.SelectedIndex = 0;
        _tip.SetToolTip(_cmbCarrier,
            "(none)  —  Payload embedded directly in the C++ source.\n" +
            "ini / png / bmp / ico  —  Payload hidden inside a decoy file;\n" +
            "the generated C++ reads the carrier at runtime.\n\n" +
            "Mutually exclusive with web mode.");
        y += Rh + Gap + 8;

        // ── Output ────────────────────────────────────────────────────
        SectionHeader("Output", ref y, W);
        _lblOutput = MakeLabel("Output file:", PadX, y); y += 20;
        _txtOutput       = MakeTextBox(PadX, y, W - 176);
        _btnBrowseOutput = MakeButton("Browse…", PadX + W - 170, y, 82, Rh);
        _btnCopyOutput   = MakeButton("⎘ Copy",  PadX + W - 82,  y, 82, Rh);
        _btnBrowseOutput.Click += BrowseOutput;
        _btnCopyOutput.Click   += CopyOutputPath;
        _tip.SetToolTip(_txtOutput,       "Path where the generated C++ snippet will be saved.");
        _tip.SetToolTip(_btnBrowseOutput, "Choose a save location.");
        _tip.SetToolTip(_btnCopyOutput,   "Copy the output path to clipboard.");
        y += Rh + Gap + 10;

        // ── Generate ──────────────────────────────────────────────────
        _btnGenerate = MakeButton("⚡  GENERATE", PadX, y, W, 40);
        _btnGenerate.Font = new Font("Segoe UI", 11F, FontStyle.Bold);
        _btnGenerate.BackColor = AccentBlue;
        _btnGenerate.FlatAppearance.BorderColor = AccentBlue;
        _btnGenerate.FlatAppearance.MouseOverBackColor = AccentHov;
        _btnGenerate.Click += Generate;
        AcceptButton = _btnGenerate;
        y += 40 + Gap;

        // ── Status ────────────────────────────────────────────────────
        _lblStatus = new Label
        {
            Text = "●  Ready",
            Location = new Point(PadX, y),
            Size = new Size(W, 18),
            ForeColor = FgDim,
            BackColor = BgDark,
            AutoSize = false,
        };
        Controls.Add(_lblStatus);
        y += 24;

        // ── Log ───────────────────────────────────────────────────────
        MakeLabel("Output log:", PadX, y + 3);
        _btnClearLog = MakeButton("Clear", PadX + W - 46, y, 46, 22);
        _btnClearLog.Font = new Font("Segoe UI", 7.5F);
        _btnClearLog.Click += (_, __) => _txtLog.Clear();
        y += 28;

        int logH = ClientSize.Height - y - 10;
        _txtLog = new RichTextBox
        {
            Location = new Point(PadX, y),
            Size = new Size(W, logH),
            ReadOnly = true,
            BackColor = LogBg,
            ForeColor = FgDim,
            BorderStyle = BorderStyle.FixedSingle,
            Font = new Font("Consolas", 8.5F),
            WordWrap = true,
            ScrollBars = RichTextBoxScrollBars.Vertical,
        };
        _txtLog.ContextMenuStrip = BuildLogMenu();
        Controls.Add(_txtLog);

        ResumeLayout();

        SetDarkTitle(Handle);
        ResolvePaths();
        if (!ValidateRequiredFiles()) return;
        LoadCatalog();
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        SetDarkTitle(Handle);
    }

    static void SetDarkTitle(IntPtr hwnd)
    {
        var v = 1;
        DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ref v, sizeof(int));
    }

    // Colored section header + thin separator line
    void SectionHeader(string title, ref int y, int w)
    {
        var upper = title.ToUpperInvariant();
        var lbl = new Label
        {
            Text = upper,
            Location = new Point(PadX, y),
            AutoSize = true,
            ForeColor = FgSection,
            BackColor = BgDark,
            Font = new Font("Segoe UI", 7.25F, FontStyle.Bold),
        };
        Controls.Add(lbl);
        // Measure after AutoSize resolves via PreferredWidth
        int sepX = PadX + lbl.PreferredWidth + 8;
        var sep = new Panel
        {
            Location = new Point(sepX, y + 7),
            Size = new Size(w - lbl.PreferredWidth - 8, 1),
            BackColor = SepColor,
        };
        Controls.Add(sep);
        y += 18;
    }

    // Dark-themed right-click menu for the log box
    ContextMenuStrip BuildLogMenu()
    {
        var cms = new ContextMenuStrip { Renderer = new DarkMenuRenderer() };
        var copy    = new ToolStripMenuItem("Copy selection"); copy.Click    += (_, __) => _txtLog.Copy();
        var copyAll = new ToolStripMenuItem("Copy all");       copyAll.Click += (_, __) => { if (_txtLog.Text.Length > 0) Clipboard.SetText(_txtLog.Text); };
        var clear   = new ToolStripMenuItem("Clear");          clear.Click   += (_, __) => _txtLog.Clear();
        cms.Items.AddRange([copy, copyAll, new ToolStripSeparator(), clear]);
        return cms;
    }

    sealed class DarkMenuRenderer : ToolStripProfessionalRenderer
    {
        public DarkMenuRenderer() : base(new DarkColorTable()) { }
        protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e)
        { e.TextColor = Color.FromArgb(212, 212, 212); base.OnRenderItemText(e); }
    }

    sealed class DarkColorTable : ProfessionalColorTable
    {
        public override Color MenuItemSelected                => Color.FromArgb(0, 122, 204);
        public override Color MenuItemSelectedGradientBegin   => Color.FromArgb(0, 122, 204);
        public override Color MenuItemSelectedGradientEnd     => Color.FromArgb(0, 122, 204);
        public override Color MenuBorder                      => Color.FromArgb(65, 65, 65);
        public override Color ToolStripDropDownBackground     => Color.FromArgb(44, 44, 44);
        public override Color ImageMarginGradientBegin        => Color.FromArgb(44, 44, 44);
        public override Color ImageMarginGradientMiddle       => Color.FromArgb(44, 44, 44);
        public override Color ImageMarginGradientEnd          => Color.FromArgb(44, 44, 44);
        public override Color MenuItemBorder                  => Color.FromArgb(0, 122, 204);
    }

    void CopyOutputPath(object? s, EventArgs e)
    {
        var p = _txtOutput.Text.Trim();
        if (p.Length > 0) Clipboard.SetText(p);
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
        if (string.IsNullOrEmpty(_scriptDir))
        {
            var exeDir = Path.GetDirectoryName(Environment.ProcessPath) ?? AppContext.BaseDirectory;
            MessageBox.Show(
                "Required script files not found.\n\n" +
                "The following files must be in the same folder as this executable:\n" +
                string.Join("\n", RequiredFiles.Select(f => "  - " + f)) +
                "\n\nLooked in: " + exeDir,
                "bin2shell — Missing Files",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            _btnGenerate.Enabled = false;
            SetStatus("Missing required files", false);
            return false;
        }

        var missing = RequiredFiles
            .Where(rel => !File.Exists(Path.Combine(_scriptDir, rel)))
            .ToList();

        if (missing.Count > 0)
        {
            MessageBox.Show(
                "Some required files are missing:\n\n" +
                string.Join("\n", missing.Select(f => "  - " + f)) +
                "\n\nThey should be in the same folder as this executable:\n" +
                _scriptDir,
                "bin2shell — Missing Files",
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
        _cmbWebHelper.Items.Clear();

        var yamlPath = _txtYaml.Text.Trim();
        if (string.IsNullOrEmpty(yamlPath) || !File.Exists(yamlPath))
        {
            _cmbEncoder.Items.Add("[0] none");
            _cmbEnvelope.Items.Add("[0] none");
            _cmbWebHelper.Items.Add("[0] winhttp");
            _cmbEncoder.SelectedIndex = 0;
            _cmbEnvelope.SelectedIndex = 0;
            _cmbWebHelper.SelectedIndex = 0;
            return;
        }

        try
        {
            var script = $@"
import json, sys, yaml
with open(r'{yamlPath.Replace("'", "\\'")}', 'r') as f:
    d = yaml.safe_load(f)
out = {{'encoders': [], 'envelopes': [], 'web_helpers': []}}
for e in d.get('encoders', []):
    out['encoders'].append({{'index': e['index'], 'name': e.get('name','')}})
for e in d.get('envelopes', []):
    out['envelopes'].append({{'index': e['index'], 'name': e.get('name','')}})
for e in d.get('web_helpers', []):
    out['web_helpers'].append({{'index': e['index'], 'name': e.get('name','')}})
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
                if (root.TryGetProperty("web_helpers", out var wh))
                    foreach (var w in wh.EnumerateArray())
                        _cmbWebHelper.Items.Add($"[{w.GetProperty("index").GetInt32()}] {w.GetProperty("name").GetString()}");
            }
        }
        catch
        {
            _cmbEncoder.Items.Add("[0] none");
            _cmbEnvelope.Items.Add("[0] none");
            _cmbWebHelper.Items.Add("[0] winhttp");
        }

        if (_cmbEncoder.Items.Count > 0)   _cmbEncoder.SelectedIndex = 0;
        if (_cmbEnvelope.Items.Count > 0)  _cmbEnvelope.SelectedIndex = 0;
        if (_cmbWebHelper.Items.Count > 0) _cmbWebHelper.SelectedIndex = 0;
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
        if (_chkWeb.Checked)
        {
            args.Add("-w");
            var whIdx = ExtractIndex(_cmbWebHelper);
            args.AddRange(["-wh", whIdx.ToString()]);
        }

        var carrierName = _cmbCarrier.SelectedItem?.ToString() ?? "(none)";
        if (carrierName != "(none)")
        {
            if (_chkWeb.Checked)
            {
                SetStatus("Web mode and Carrier are mutually exclusive", false);
                _btnGenerate.Enabled = true;
                return;
            }
            args.AddRange(["--carrier", carrierName]);
            var carrierOutDir = Path.GetDirectoryName(outputPath) ?? _scriptDir;
            var carrierPath = Path.Combine(carrierOutDir, "payload." + carrierName);
            args.AddRange(["--carrier-out", carrierPath]);
        }

        args.AddRange(["-o", outputPath]);
        args.Add(inputPath);

        var outDir = Path.GetDirectoryName(outputPath);
        if (!string.IsNullOrEmpty(outDir) && !Directory.Exists(outDir))
            Directory.CreateDirectory(outDir);

        _btnGenerate.Enabled = false;
        _btnGenerate.Text = "⏳  Generating…";
        SetStatus("Generating…", true);
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
            proc.ErrorDataReceived  += (_, d) => { if (d.Data != null) sbErr.AppendLine(d.Data); };

            proc.Start();
            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
            await proc.WaitForExitAsync();

            if (!string.IsNullOrWhiteSpace(sbErr.ToString())) Log(sbErr.ToString().TrimEnd());
            if (!string.IsNullOrWhiteSpace(sbOut.ToString())) Log(sbOut.ToString().TrimEnd());

            if (proc.ExitCode == 0)
            {
                var fi = new FileInfo(outputPath);
                SetStatus($"Done — {fi.Length:N0} bytes → {fi.Name}", true);
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
        finally
        {
            _btnGenerate.Enabled = true;
            _btnGenerate.Text = "⚡  GENERATE";
        }
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
            Title = "Select algorithms playbook",
            Filter = "YAML files (*.yaml;*.yml)|*.yaml;*.yml|All files (*.*)|*.*",
        };
        if (dlg.ShowDialog() == DialogResult.OK)
        {
            _txtYaml.Text = dlg.FileName;
            LoadCatalog();
        }
    }

    void WebModeToggled(object? s, EventArgs e)
    {
        _lblWebHelper.Enabled = _chkWeb.Checked;
        _cmbWebHelper.Enabled = _chkWeb.Checked;
    }

    void SetStatus(string msg, bool ok)
    {
        _lblStatus.Text = "●  " + msg;
        _lblStatus.ForeColor = ok ? GreenOk : RedErr;
    }

    void Log(string msg) => _txtLog.AppendText(msg + Environment.NewLine);

    // ── Factory helpers ───────────────────────────────────────────────

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
            Size = new Size(w, 26),
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
            BackColor = BgButton,
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
            var isSelected = (e.State & DrawItemState.Selected) != 0;
            var bg = isSelected ? AccentBlue : BgField;
            using var bgBrush = new SolidBrush(bg);
            using var fgBrush = new SolidBrush(cmb.Enabled ? FgText : FgDim);
            e.Graphics.FillRectangle(bgBrush, e.Bounds);
            var text = cmb.Items[e.Index]?.ToString() ?? "";
            e.Graphics.DrawString(text, cmb.Font, fgBrush,
                new RectangleF(e.Bounds.X + 6, e.Bounds.Y + 2, e.Bounds.Width - 8, e.Bounds.Height));
        };
        Controls.Add(cmb);
        return cmb;
    }
}
