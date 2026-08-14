using System;
using System.Collections.Generic;
using System.Text;
using System.Threading;
using Intelligence;
using Package;

class LiveProbe
{
    static Dictionary<string, int> statusCounts = new Dictionary<string, int>();
    static Dictionary<string, int> messageCounts = new Dictionary<string, int>();
    static ManualResetEventSlim loginReady = new ManualResetEventSlim(false);
    static ManualResetEventSlim loginFailed = new ManualResetEventSlim(false);

    static void Log(string msg)
    {
        Console.WriteLine("[" + DateTime.Now.ToString("s") + "] " + msg);
        Console.Out.Flush();
    }

    static void Bump(Dictionary<string, int> d, string key)
    {
        int v;
        d.TryGetValue(key, out v);
        d[key] = v + 1;
    }

    static void OnStatus(object sender, COM_STATUS status, byte[] msg)
    {
        string name = status.ToString();
        Bump(statusCounts, name);
        string smsg;
        try { smsg = Encoding.UTF8.GetString(msg); } catch { smsg = "<binary>"; }
        Log("STATUS " + name + ": " + smsg);

        if (status == COM_STATUS.LOGIN_READY) loginReady.Set();
        if (status == COM_STATUS.LOGIN_FAIL || status == COM_STATUS.LOGIN_UNKNOW) loginFailed.Set();
    }

    static void OnMessage(object sender, PackageBase pkg)
    {
        string dtName = pkg.DT.ToString();
        Bump(messageCounts, dtName);
        if (pkg.DT == (ushort)DT.QUOTE_STOCK_MATCH1 || pkg.DT == (ushort)DT.QUOTE_STOCK_MATCH2)
        {
            dynamic p = pkg;
            Log("MATCH " + p.StockNo + ": price=" + p.Match_Price + " qty=" + p.Match_Qty + " total=" + p.Total_Qty);
        }
        else
        {
            Log("MESSAGE DT=" + dtName);
        }
    }

    static int Main(string[] args)
    {
        try
        {
            string token = Environment.GetEnvironmentVariable("KGI_TOKEN");
            string sid = Environment.GetEnvironmentVariable("KGI_SID") ?? "API";
            string userId = Environment.GetEnvironmentVariable("KGI_USER_ID");
            string password = Environment.GetEnvironmentVariable("KGI_PASSWORD");
            string host = Environment.GetEnvironmentVariable("KGI_QUOTE_HOST") ?? "iquotetest.kgi.com.tw";
            ushort port = ushort.Parse(Environment.GetEnvironmentVariable("KGI_QUOTE_PORT") ?? "8000");
            string stockCode = Environment.GetEnvironmentVariable("PROBE_STOCK_CODE") ?? "2330";
            int durationSec = int.Parse(Environment.GetEnvironmentVariable("PROBE_DURATION_SEC") ?? "90");

            Log("Connecting: host=" + host + " port=" + port + " sid=" + sid + " stock=" + stockCode + " duration=" + durationSec + "s");

            QuoteCom quoteCom = new QuoteCom("", 443, sid, token);
            quoteCom.OnRcvMessage += OnMessage;
            quoteCom.OnGetStatus += OnStatus;

            quoteCom.Connect2Quote(host, port, userId, password, ' ', "");

            Log("Connect2Quote called, waiting for LOGIN_READY / LOGIN_FAIL...");
            int waited = WaitHandle.WaitAny(new WaitHandle[] { loginReady.WaitHandle, loginFailed.WaitHandle }, TimeSpan.FromSeconds(20));
            if (waited == WaitHandle.WaitTimeout)
            {
                Log("Timed out waiting for login status — aborting probe.");
                quoteCom.Dispose();
                return 1;
            }
            if (loginFailed.IsSet)
            {
                Log("Login failed — aborting probe.");
                quoteCom.Dispose();
                return 1;
            }

            Log("Subscribing to " + stockCode + " (match + depth)...");
            Log("SubQuotesMatch: " + quoteCom.SubQuotesMatch(stockCode));
            Log("SubQuotesDepth: " + quoteCom.SubQuotesDepth(stockCode));

            Log("Listening for " + durationSec + "s — watching for MATCH/MESSAGE lines above...");
            Thread.Sleep(durationSec * 1000);

            quoteCom.UnSubQuotesMatch(stockCode);
            quoteCom.UnSubQuotesDepth(stockCode);
            quoteCom.Logout();
            Thread.Sleep(2000);
            quoteCom.Dispose();

            Log("=== SUMMARY ===");
            Log("Status events: " + Dump(statusCounts));
            Log("Message events: " + Dump(messageCounts));

            if (messageCounts.Count == 0)
            {
                Log("NO DATA RECEIVED - login/connect worked but no ticks came through the callback.");
                return 2;
            }

            Log("Ticks were received via the callback - quote path works in this container.");
            return 0;
        }
        catch (Exception ex)
        {
            Log("UNHANDLED EXCEPTION:");
            Log(ex.ToString());
            return 1;
        }
    }

    static string Dump(Dictionary<string, int> d)
    {
        var parts = new List<string>();
        foreach (var kv in d) parts.Add(kv.Key + "=" + kv.Value);
        return "{" + string.Join(", ", parts) + "}";
    }
}
