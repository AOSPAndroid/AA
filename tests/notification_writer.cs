using System;
using System.IO;
using Atlas.Notifications;
class NotificationWriterTests
{
    static void Assert(bool value, string reason) { if (!value) throw new Exception(reason); }
    static void Main(string[] args)
    {
        // Test runner supplies its isolated temporary queue. Never uses defaults
        // or requests Windows notification permission.
        if (args.Length != 1 || !Directory.Exists(args[0])) throw new Exception("Supply an isolated test directory");
        var settings = new Settings();
        var controlPath = Path.Combine(args[0], "notifications-command.json");
        JsonFile.Write(controlPath, new { id="fixture",operation="pause_show",outlook_previews=false,expires_at=DateTimeOffset.UtcNow.AddSeconds(30).ToString("o") });
        Assert(ListenerCommand.Read(controlPath).operation == "pause_show", "Known command accepted");
        JsonFile.Write(controlPath, new { id="fixture",operation="execute",expires_at=DateTimeOffset.UtcNow.AddSeconds(30).ToString("o") });
        Assert(ListenerCommand.Read(controlPath) == null, "Arbitrary commands rejected");
        JsonFile.Write(controlPath, new { id="fixture",operation="start",expires_at=DateTimeOffset.UtcNow.AddSeconds(-1).ToString("o") });
        Assert(ListenerCommand.Read(controlPath) == null, "Expired command rejected");
        File.WriteAllText(controlPath, "not json");
        Assert(ListenerCommand.Read(controlPath) == null, "Corrupt command ignored");
        Assert(settings.Source("MSTeams_8wekyb3d8bbwe!MSTeams") == "teams", "Teams source");
        Assert(settings.Source("Chrome") == null && settings.Source("UnrelatedApp") == null, "Unrelated notifications excluded");
        Assert(settings.Source("Microsoft.Office.OUTLOOK.EXE.15") == null, "Outlook previews opt-in");
        settings.OutlookEnabled = true;
        Assert(settings.Source("Microsoft.Office.OUTLOOK.EXE.15") == "outlook", "Outlook opt-in");
        var created = new DateTimeOffset(2026,10,15,10,0,0,TimeSpan.Zero);
        using (var queue = new QueueStore(args[0]))
        {
            var since = queue.Since(); Assert(queue.Since() == since, "Start boundary stable");
            Assert(queue.Add("teams","MSTeams_8wekyb3d8bbwe!MSTeams","Microsoft Teams",7,created,new[] { "Sam Green", "VPN cannot connect. <script>no()</script>\nUnicode: café 中文" }), "First preview");
            Assert(!queue.Add("teams","MSTeams_8wekyb3d8bbwe!MSTeams","Microsoft Teams",7,created,new[] { "Sam Green", "VPN cannot connect. <script>no()</script>\nUnicode: café 中文" }), "Deduplicated preview");
            Assert(queue.Add("teams","MSTeams_8wekyb3d8bbwe!MSTeams","Microsoft Teams",7,created,new[] { "Sam Green", "Updated notification text" }), "Changed preview preserved");
            Assert(queue.Add("teams","MSTeams_8wekyb3d8bbwe!MSTeams","Microsoft Teams",7,created.AddMinutes(1),new[] { "Sam Green", "Updated notification text" }), "Reused Windows ID preserved");
            Assert(queue.Add("outlook","Microsoft.Office.OUTLOOK.EXE.15","Outlook",9,created,new[] { "Alex Morgan", "A notification preview" }), "Outlook source");
            Assert(queue.Add("teams","MSTeams_8wekyb3d8bbwe!MSTeams","Microsoft Teams",10,created,new string[0]), "Missing title/body safe");
        }
        using (var queue = new QueueStore(args[0]))
            Assert(!queue.Add("teams","MSTeams_8wekyb3d8bbwe!MSTeams","Microsoft Teams",7,created,new[] { "Sam Green", "Updated notification text" }), "Restart deduplicated");
        using (var held = new FileStream(Path.Combine(args[0],"notifications.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.ReadWrite)) { held.Lock(0,1); held.WriteByte(0); held.Flush(); }
        JsonFile.Write(Path.Combine(args[0],"notifications-status.json"), new { state="watching",updated_at=DateTimeOffset.UtcNow.ToString("o"),captured=5 });
        Console.WriteLine("PASS: Windows SQLite writer, source filtering, Unicode, deduplication, replacement previews, ID reuse, restart and status output");
    }
}
