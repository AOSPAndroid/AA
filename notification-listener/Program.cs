using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Security.Principal;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Windows.Foundation;
using Windows.UI.Notifications;
using Windows.UI.Notifications.Management;
using Size = System.Drawing.Size;

namespace Atlas.Notifications
{
    internal static class Program
    {
        [STAThread]
        private static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            try
            {
                if (new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator))
                    throw new InvalidOperationException("Start the listener normally as the Teams/Outlook user, not from elevated Atlas.");
                // Windows consent is attached to this installed identity.
                string identity = Windows.ApplicationModel.Package.Current.Id.Name;
                string directory = null;
                bool autoStart = false, background = false;
                for (int i = 0; i < args.Length; i++)
                {
                    if (args[i] == "--data-dir" && i + 1 < args.Length) directory = args[++i];
                    else if (args[i] == "--auto-start") autoStart = true;
                    else if (args[i] == "--background") background = true;
                    else throw new ArgumentException("Unknown listener option.");
                }
                Application.Run(new ListenerForm(directory, autoStart, background));
            }
            catch (Exception error)
            {
                MessageBox.Show("Atlas notification listener could not start.\nInstall/register its package for the normal Teams/Outlook account.\n\n" + error.Message,
                                "Atlas notifications", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
        }
    }
    internal sealed class SourceChoice
    {
        public string Id, Name;
        public override string ToString() { return Name + "  [" + Id + "]"; }
    }
    internal sealed class ListenerForm : Form
    {
        private readonly Label statusLabel = new Label { AutoSize = false, Height = 68, Dock = DockStyle.Top };
        private readonly Button start = new Button { Text = "Allow access and start", AutoSize = true };
        private readonly Button stop = new Button { Text = "Pause", AutoSize = true };
        private readonly CheckBox outlook = new CheckBox { Text = "Also capture Outlook notification previews", AutoSize = true };
        private readonly ComboBox apps = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 620 };
        private readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer { Interval = 2000 };
        private readonly CancellationTokenSource lifetime = new CancellationTokenSource();
        private readonly NotifyIcon tray;
        private readonly string settingsPath, directory;
        private readonly Settings settings;
        private readonly FileStream processLock;
        private QueueStore store;
        private UserNotificationListener listener;
        private bool busy, collecting, closing;
        private int captured, teamsSeen, outlookSeen, intent;
        private string lastCommand;
        private string state = "stopped", detail = "Select Allow access and start. Windows will request notification permission.", lastSuccess;
        private DateTimeOffset since;

        public ListenerForm(string requestedDirectory, bool autoStart, bool background)
        {
            var local = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Atlas", "NotificationListener");
            System.IO.Directory.CreateDirectory(local);
            settingsPath = Path.Combine(local, "settings.json");
            settings = File.Exists(settingsPath) ? new JavaScriptSerializer().Deserialize<Settings>(File.ReadAllText(settingsPath)) : new Settings();
            string requested = requestedDirectory ?? settings.Directory ?? Environment.GetEnvironmentVariable("ATLAS_MAIL_DIR");
            directory = Path.GetFullPath(requested ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Atlas", "OutlookWatcher"));
            if (directory.StartsWith(@"\\", StringComparison.Ordinal)) throw new InvalidOperationException("Use a local folder on this PC.");
            if (requested != null && !System.IO.Directory.Exists(directory)) throw new DirectoryNotFoundException("The configured bridge folder does not exist. Run Configure-Outlook-Bridge.ps1 under the Atlas account first.");
            System.IO.Directory.CreateDirectory(directory);
            processLock = new FileStream(Path.Combine(directory, "notifications.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.ReadWrite);
            try
            {
                processLock.Lock(0, 1);
                if (processLock.Length == 0) { processLock.WriteByte(0); processLock.Flush(); }
            }
            catch { processLock.Dispose(); throw new InvalidOperationException("A notification listener already owns this queue."); }
            settings.Directory = directory;
            Text = "Atlas · Notification listener";
            Font = new Font("Segoe UI", 9);
            ClientSize = new Size(680, 420); MinimumSize = new Size(620, 420);
            var layout = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false, AutoScroll = true, Padding = new Padding(12) };
            Controls.Add(layout);
            layout.Controls.Add(new Label { Text = "Teams and Outlook → Atlas Live Inbox", AutoSize = true, Font = new Font(Font, FontStyle.Bold) });
            layout.Controls.Add(new Label { Text = WindowsIdentity.GetCurrent().Name + "\nQueue: " + directory, Width = 640, Height = 46 });
            layout.Controls.Add(new Label { Text = "Windows permission exposes notifications to this listener. Only selected Teams/Outlook sources are saved locally.\nPreviews can be incomplete; messages without a Windows notification cannot be captured.", Width = 640, Height = 48 });
            statusLabel.Width = 640; layout.Controls.Add(statusLabel);
            var actions = new FlowLayoutPanel { AutoSize = true };
            actions.Controls.Add(start); actions.Controls.Add(stop); layout.Controls.Add(actions);
            outlook.Checked = settings.OutlookEnabled; layout.Controls.Add(outlook);
            layout.Controls.Add(new Label { Text = "Source check: apps currently exposed by Windows (no other app content is saved).", AutoSize = true });
            layout.Controls.Add(apps);
            var sources = new FlowLayoutPanel { AutoSize = true };
            var useTeams = new Button { Text = "Use selected app as Teams", AutoSize = true };
            var useOutlook = new Button { Text = "Use selected app as Outlook", AutoSize = true };
            sources.Controls.Add(useTeams); sources.Controls.Add(useOutlook); layout.Controls.Add(sources);
            layout.Controls.Add(new Label { Text = "If Teams is missing, generate a Teams test notification. App-only banners need a different connector.\nMinimize to keep listening in the tray. Closing this window stops the listener.", Width = 640, Height = 44 });
            var menu = new ContextMenuStrip();
            menu.Items.Add("Open Atlas listener", null, (s, e) => Restore());
            menu.Items.Add("Exit", null, (s, e) => Close());
            tray = new NotifyIcon { Icon = SystemIcons.Information, Text = "Atlas notifications", Visible = true, ContextMenuStrip = menu };
            tray.DoubleClick += (s, e) => Restore();
            Resize += (s, e) => { if (WindowState == FormWindowState.Minimized) Hide(); };
            start.Click += async (s, e) => await StartListening(true);
            stop.Click += (s, e) => Pause();
            outlook.CheckedChanged += (s, e) => { settings.OutlookEnabled = outlook.Checked; SaveSettings(); Publish(); };
            useTeams.Click += (s, e) => SelectSource(true);
            useOutlook.Click += (s, e) => SelectSource(false);
            timer.Tick += async (s, e) => { await ApplyControl(); if (closing) return; if (collecting) await Sync(); else Publish(); };
            Shown += async (s, e) => {
                if (background) { WindowState = FormWindowState.Minimized; Hide(); }
                bool controlled = await ApplyControl();
                if (autoStart && !controlled && !closing) await StartListening(false);
            };
            FormClosing += OnClosing;
            SaveSettings(); Publish(); timer.Start();
        }
        private void Restore() { Show(); WindowState = FormWindowState.Normal; Activate(); }
        private void Pause()
        {
            intent++; collecting = false; state = "stopped"; detail = "Notification collection paused."; Publish();
        }
        private async Task<bool> ApplyControl()
        {
            if (closing) return false;
            var command = ListenerCommand.Read(Path.Combine(directory, "notifications-command.json"));
            if (command == null || command.id == lastCommand) return false;
            if (busy && command.operation.StartsWith("start"))
            {
                if (command.operation.EndsWith("_show")) Restore();
                return false; // Retry after the pending WinRT operation completes.
            }
            lastCommand = command.id;
            outlook.Checked = command.outlook_previews;
            if (command.operation == "exit") { Close(); return true; }
            if (command.operation.EndsWith("_show")) Restore();
            if (command.operation.StartsWith("pause")) Pause();
            else await StartListening(false);
            return true;
        }
        private void SaveSettings() { JsonFile.Write(settingsPath, settings); }
        private void SelectSource(bool teams)
        {
            var selected = apps.SelectedItem as SourceChoice;
            if (selected == null) return;
            // Browsers combine notifications from many sites; never select an
            // entire browser as Teams/Outlook or infer origin from message text.
            string label = selected.Name.ToLowerInvariant(), id = selected.Id.ToLowerInvariant();
            if (new[] { "chrome", "edge", "firefox", "opera", "brave", "vivaldi", "browser" }.Any(word => label.Contains(word) || id.Contains(word)))
            { MessageBox.Show("Browser-wide capture is not supported. Select the installed Teams or Outlook app."); return; }
            if (MessageBox.Show("Save notifications from " + selected.Name + " as " + (teams ? "Teams" : "Outlook") + " previews?",
                                "Choose notification source", MessageBoxButtons.OKCancel) != DialogResult.OK) return;
            if (teams) settings.ExtraTeamsId = selected.Id; else { settings.ExtraOutlookId = selected.Id; outlook.Checked = true; }
            SaveSettings();
        }
        // Keep WinRT operations on this STA UI thread without requiring an
        // additional .NET runtime on the target PC. Never block its message pump.
        private async Task<T> Await<T>(IAsyncOperation<T> operation, int timeoutSeconds)
        {
            var deadline = DateTimeOffset.UtcNow.AddSeconds(timeoutSeconds);
            try
            {
                while (operation.Status == AsyncStatus.Started)
                {
                    lifetime.Token.ThrowIfCancellationRequested();
                    if (DateTimeOffset.UtcNow > deadline) throw new TimeoutException("Windows notification access timed out.");
                    await Task.Delay(50, lifetime.Token);
                }
                return operation.GetResults();
            }
            finally { if (operation.Status == AsyncStatus.Started) operation.Cancel(); operation.Close(); }
        }
        private async Task StartListening(bool requestPermission)
        {
            if (busy || collecting) return;
            busy = true; start.Enabled = false;
            int requestedIntent = ++intent;
            state = "starting"; detail = "Waiting for Windows notification permission."; Publish();
            try
            {
                listener = UserNotificationListener.Current;
                var access = requestPermission ? await Await(listener.RequestAccessAsync(), 300) : listener.GetAccessStatus();
                if (closing || requestedIntent != intent) return;
                if (access != UserNotificationListenerAccessStatus.Allowed)
                {
                    state = "permission_required";
                    detail = "Open Listener settings in Atlas and select Allow access and start to grant Windows notification permission.";
                    return;
                }
                if (store == null) store = new QueueStore(directory);
                since = store.Since(); collecting = true;
                state = "watching"; detail = "Listening for Windows notification previews.";
            }
            catch (OperationCanceledException) { }
            catch (Exception error) { state = "error"; detail = error.Message; }
            finally { busy = false; if (!closing) { start.Enabled = true; Publish(); } }
            if (collecting && !closing) await Sync();
        }
        private async Task Sync()
        {
            if (busy || closing || !collecting) return;
            busy = true;
            try
            {
                if (listener.GetAccessStatus() != UserNotificationListenerAccessStatus.Allowed)
                { collecting = false; state = "permission_required"; detail = "Windows notification access was revoked. Grant access and start again."; return; }
                var notifications = await Await(listener.GetNotificationsAsync(NotificationKinds.Toast), 20);
                if (closing || !collecting) return;
                if (listener.GetAccessStatus() != UserNotificationListenerAccessStatus.Allowed)
                { collecting = false; state = "permission_required"; detail = "Windows notification access was revoked."; return; }
                var choices = new Dictionary<string, SourceChoice>();
                teamsSeen = 0; outlookSeen = 0; int failures = 0;
                foreach (var notification in notifications.OrderBy(item => item.CreationTime))
                {
                    try
                    {
                        string id = notification.AppInfo.AppUserModelId;
                        string name = notification.AppInfo.DisplayInfo.DisplayName;
                        choices[id] = new SourceChoice { Id = id, Name = name };
                        string source = settings.Source(id);
                        if (source == null) continue;
                        if (source == "teams") teamsSeen++; else outlookSeen++;
                        if (notification.CreationTime < since) continue;
                        var binding = notification.Notification.Visual.GetBinding(KnownNotificationBindings.ToastGeneric);
                        if (binding == null) continue;
                        if (store.Add(source, id, name, notification.Id, notification.CreationTime, binding.GetTextElements().Select(t => t.Text).ToArray())) captured++;
                    }
                    catch { failures++; } // One vanished/protected notification must not starve the rest.
                }
                string selected = (apps.SelectedItem as SourceChoice ?? new SourceChoice()).Id;
                apps.BeginUpdate(); apps.Items.Clear();
                apps.Items.AddRange(choices.Values.OrderBy(item => item.Name).Cast<object>().ToArray());
                apps.SelectedItem = choices.ContainsKey(selected ?? "") ? choices[selected] : null;
                apps.EndUpdate();
                lastSuccess = DateTimeOffset.UtcNow.ToString("o"); state = failures == 0 ? "watching" : "retrying";
                detail = failures == 0 ? "Listening. Teams alerts visible to Windows: " + teamsSeen + ". Captured this run: " + captured + "." : failures + " notification(s) could not be read or saved; retrying.";
            }
            catch (OperationCanceledException) { }
            catch (Exception error) { state = "retrying"; detail = error.Message; }
            finally { busy = false; if (!closing) Publish(); }
        }
        private void Publish()
        {
            if (closing) return;
            statusLabel.Text = state + " · " + detail;
            try
            {
                JsonFile.Write(Path.Combine(directory, "notifications-status.json"), new {
                    state = state, detail = detail, updated_at = DateTimeOffset.UtcNow.ToString("o"), last_success_at = lastSuccess,
                    captured = captured, teams_seen = teamsSeen, outlook_seen = outlookSeen, outlook_enabled = settings.OutlookEnabled
                });
            }
            catch (Exception error) { collecting = false; state = "error"; statusLabel.Text = "Cannot write the Atlas queue status: " + error.Message; }
        }
        private void OnClosing(object sender, FormClosingEventArgs e)
        {
            collecting = false; state = "stopped"; detail = "Notification listener closed."; Publish();
            closing = true; lifetime.Cancel(); timer.Stop(); timer.Dispose(); tray.Dispose();
            if (store != null) store.Dispose();
            processLock.Dispose();
        }
    }
}
