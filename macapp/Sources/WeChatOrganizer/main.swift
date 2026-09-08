import AppKit
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var output: Pipe?
    var quitting = false
    var ready = false
    var startupText = ""
    let baseURL = URL(string: "http://127.0.0.1:8876/")!
    var resources: URL { Bundle.main.resourceURL!.appendingPathComponent("bridge") }
    var data: URL { FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("com.baiya.WeChatOrganizer") }
    var backend: URL { Bundle.main.resourceURL!.appendingPathComponent("backend/WeChatBridge") }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        if let iconURL=Bundle.main.url(forResource:"AppIcon",withExtension:"icns"),let icon=NSImage(contentsOf:iconURL) {NSApp.applicationIconImage=icon}
        let menu = NSMenu(), appItem = NSMenuItem();menu.addItem(appItem)
        let appMenu = NSMenu();appItem.submenu=appMenu
        appMenu.addItem(withTitle: "关于公众号整理", action: #selector(about), keyEquivalent: "")
        appMenu.addItem(withTitle: "重新加载页面", action: #selector(reload), keyEquivalent: "r")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出公众号整理", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem=NSMenuItem();menu.addItem(editItem);let edit=NSMenu(title:"编辑");editItem.submenu=edit
        edit.addItem(withTitle:"拷贝",action:#selector(NSText.copy(_:)),keyEquivalent:"c")
        edit.addItem(withTitle:"粘贴",action:#selector(NSText.paste(_:)),keyEquivalent:"v")
        edit.addItem(withTitle:"全选",action:#selector(NSText.selectAll(_:)),keyEquivalent:"a")
        NSApp.mainMenu=menu
        let config=WKWebViewConfiguration();config.userContentController.add(self,name:"environment")
        web=WKWebView(frame:.zero,configuration:config);web.navigationDelegate=self
        window=NSWindow(contentRect:NSRect(x:0,y:0,width:1150,height:820),styleMask:[.titled,.closable,.miniaturizable,.resizable],backing:.buffered,defer:false)
        window.title="公众号整理";window.minSize=NSSize(width:760,height:620);window.contentView=web;window.center();window.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)
        showStatus("正在启动", "正在检查本机环境并启动内置服务。")
        startServer()
    }
    func showStatus(_ title:String,_ detail:String) {
        let escaped=detail.replacingOccurrences(of:"&",with:"&amp;").replacingOccurrences(of:"<",with:"&lt;")
        web.loadHTMLString("<html><meta charset='utf-8'><body style='background:#f5f7f6;color:#183329;font:17px -apple-system;padding:70px'><h1>\(title)</h1><p>\(escaped)</p></body></html>",baseURL:nil)
    }
    func startServer() {
        do {
            try FileManager.default.createDirectory(at:data,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
            let process=Process();process.executableURL=backend
            var env=ProcessInfo.processInfo.environment
            env["WECHAT_RESOURCES"]=resources.path;env["WECHAT_DATA_ROOT"]=data.path
            env["WECHAT_NODE"]=Bundle.main.resourceURL!.appendingPathComponent("node").path
            env["WECHAT_DEBUGGER"]=Bundle.main.resourceURL!.appendingPathComponent("debugger").path
            process.environment=env
            let pipe=Pipe();process.standardOutput=pipe;process.standardError=pipe;output=pipe;server=process
            pipe.fileHandleForReading.readabilityHandler={ [weak self] handle in
                let bytes=handle.availableData;guard !bytes.isEmpty,let text=String(data:bytes,encoding:.utf8) else{return}
                DispatchQueue.main.async {
                    guard let self=self else{return};self.startupText+=text
                    if !self.ready && self.startupText.contains("READY http://127.0.0.1:8876") {self.ready=true;self.web.load(URLRequest(url:self.baseURL))}
                }
            }
            process.terminationHandler={ [weak self] _ in DispatchQueue.main.async {
                guard let self=self else{return}
                if self.quitting {NSApp.reply(toApplicationShouldTerminate:true)} else {self.ready=false;self.showStatus("服务未能运行", "请关闭旧版网页工具或其他占用端口的程序，再重新打开应用。当前没有执行取关。")}
            }}
            try process.run()
        } catch {showStatus("无法启动内置服务",error.localizedDescription)}
    }
    @objc func reload(){if ready{web.load(URLRequest(url:baseURL))}}
    @objc func about(){let a=NSAlert();a.messageText="公众号整理 · 本机内测版";a.informativeText="使用固定版本 WMPFDebugger（GPLv2）及 Frida。仅在经过验证的微信环境中运行。数据保存在本机，未知版本暂停接入。\n上游：https://github.com/evi0s/WMPFDebugger\n完整源码及许可位于应用 Resources/Source。";a.runModal()}
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool {true}
    func applicationShouldTerminate(_ sender:NSApplication)->NSApplication.TerminateReply {
        guard let process=server,process.isRunning else{return .terminateNow}
        if quitting{return .terminateLater}
        quitting=true
        showStatus("正在安全退出", "当前账号如已开始处理，将等待复核完成；后续账号不会继续执行。")
        process.terminate() // Service handles SIGTERM: stop queue, finish current item, detach its debugger.
        return .terminateLater
    }
    func webView(_ webView:WKWebView,decidePolicyFor navigationAction:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void){
        guard let url=navigationAction.request.url else{decisionHandler(.cancel);return}
        decisionHandler(url.scheme=="about" || (url.host=="127.0.0.1" && url.port==8876) ? .allow:.cancel)
    }
    func userContentController(_ userContentController:WKUserContentController,didReceive message:WKScriptMessage){
        guard message.frameInfo.isMainFrame, message.frameInfo.request.url?.host=="127.0.0.1",message.frameInfo.request.url?.port==8876,let action=message.body as? String,["prepare","restore"].contains(action) else{return}
        let alert=NSAlert();alert.messageText=action=="prepare" ? "准备微信连接环境":"恢复微信原始文件"
        alert.informativeText=action=="prepare" ? "这会备份并调整已验证版本的微信辅助程序签名。不会读取聊天内容或关闭系统保护。请先完全退出微信；接下来由系统请求管理员授权。" : "将关闭本工具的连接，并把微信辅助程序恢复为本机备份的原始文件。请先完全退出微信；版本不匹配时会拒绝覆盖。"
        alert.addButton(withTitle:action=="prepare" ? "准备并授权":"恢复并授权");alert.addButton(withTitle:"取消")
        guard alert.runModal() == .alertFirstButtonReturn else{return}
        Task { await environmentAction(action) }
    }
    func request(_ endpoint:String) async throws {
        let json=try JSONSerialization.jsonObject(with:Data(contentsOf:data.appendingPathComponent("web-token.json"))) as! [String:String]
        var req=URLRequest(url:baseURL.appendingPathComponent(endpoint));req.httpMethod="POST";req.httpBody=Data("{}".utf8)
        req.setValue("http://127.0.0.1:8876",forHTTPHeaderField:"Origin");req.setValue(json["token"],forHTTPHeaderField:"X-Selection-Token");req.setValue("application/json",forHTTPHeaderField:"Content-Type")
        let (bytes,response)=try await URLSession.shared.data(for:req)
        guard (response as? HTTPURLResponse)?.statusCode==200 else {
            let result=(try? JSONSerialization.jsonObject(with:bytes)) as? [String:Any]
            throw NSError(domain:"WeChatOrganizer",code:1,userInfo:[NSLocalizedDescriptionKey:result?["error"] as? String ?? "请先停止队列并等待当前账号完成"])
        }
    }
    func shellQuote(_ s:String)->String {"'"+s.replacingOccurrences(of:"'",with:"'\\''")+"'"}
    func appleString(_ s:String)->String {"\""+s.replacingOccurrences(of:"\\",with:"\\\\").replacingOccurrences(of:"\"",with:"\\\"")+"\""}
    nonisolated static func runPrepare(backend: URL, data: URL, resources: URL) throws {
        let p=Process();p.executableURL=backend;p.arguments=["--environment","prepare","--data",data.path,"--resources",resources.path]
        let out=Pipe();p.standardOutput=out;p.standardError=out;try p.run();p.waitUntilExit()
        let bytes=out.fileHandleForReading.readDataToEndOfFile()
        if p.terminationStatus != 0 {let result=(try? JSONSerialization.jsonObject(with:bytes)) as? [String:Any];throw NSError(domain:"Prepare",code:1,userInfo:[NSLocalizedDescriptionKey:result?["error"] as? String ?? "准备失败，未修改微信"])}
    }
    @MainActor func environmentAction(_ action:String) async {
        do {
            try await request("api/disconnect")
            if action=="prepare" {let b=backend,d=data,r=resources;try await Task.detached {try Self.runPrepare(backend:b,data:d,resources:r)}.value}
            let args=[backend.path,"--environment",action=="prepare" ? "apply":"restore","--data",data.path,"--resources",resources.path]
            let command=args.map(shellQuote).joined(separator:" ")
            var error:NSDictionary?
            let result=NSAppleScript(source:"do shell script \(appleString(command)) with administrator privileges")?.executeAndReturnError(&error)
            if let error=error {throw NSError(domain:"Environment",code:1,userInfo:[NSLocalizedDescriptionKey:error[NSAppleScript.errorMessage] as? String ?? "系统未允许修改，微信文件未确认改变"])}
            let value=(try? JSONSerialization.jsonObject(with:Data((result?.stringValue ?? "{}").utf8))) as? [String:Any]
            if let reason=value?["error"] as? String {throw NSError(domain:"Environment",code:1,userInfo:[NSLocalizedDescriptionKey:reason])}
            let alert=NSAlert();alert.messageText=value?["message"] as? String ?? "处理完成";alert.informativeText="请重新打开微信，再点击连接。";alert.runModal();reload()
        } catch {let alert=NSAlert();alert.messageText="操作未完成";alert.informativeText=error.localizedDescription;alert.runModal()}
    }
}
let app=NSApplication.shared
let delegate=AppDelegate();app.delegate=delegate;app.run()
