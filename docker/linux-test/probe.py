import sys
import traceback

sys.path.append("/app")

import clr  # noqa: E402

print(f"pythonnet runtime: {clr.__file__}")

try:
    clr.AddReference("System.Text.Encoding.CodePages")
    from System.Text import Encoding, CodePagesEncodingProvider
    Encoding.RegisterProvider(CodePagesEncodingProvider.Instance)
    print("Registered CodePagesEncodingProvider (Big5/GBK/etc. support)")
except Exception:
    print("Could not register CodePagesEncodingProvider:")
    traceback.print_exc()

def step(name, fn):
    print(f"\n--- {name} ---")
    try:
        result = fn()
        print(f"OK: {result}")
        return result, True
    except Exception:
        print("FAILED:")
        traceback.print_exc()
        return None, False

step("AddReference Package", lambda: clr.AddReference("Package"))
step("AddReference PushClient", lambda: clr.AddReference("PushClient"))
step("AddReference QuoteCom", lambda: clr.AddReference("QuoteCom"))
step("AddReference Interop.KGICGCAPIATLLib", lambda: clr.AddReference("Interop.KGICGCAPIATLLib"))
step("AddReference TradeCom", lambda: clr.AddReference("TradeCom"))

def do_imports():
    global PackageBase, P001503, PushClient, QuoteCom, COM_STATUS, DT, IdxKind
    from Package import PackageBase, P001503
    from Intelligence import PushClient, QuoteCom, COM_STATUS, DT, IdxKind
    return "namespace imports succeeded"

step("import Package/Intelligence namespaces", do_imports)

def instantiate_quotecom():
    global quote_obj
    quote_obj = QuoteCom("", 443, "API", "b6eb")
    return f"instantiated QuoteCom object: {quote_obj}"

_, quote_ok = step("instantiate QuoteCom() (no network call)", instantiate_quotecom)

def wire_events():
    def on_status(sender, status, msg):
        pass
    def on_msg(sender, pkg):
        pass
    quote_obj.OnRcvMessage += on_msg
    quote_obj.OnGetStatus += on_status
    return "event handlers wired"

if quote_ok:
    step("wire OnRcvMessage/OnGetStatus event handlers", wire_events)

print("\n=== probe complete ===")
