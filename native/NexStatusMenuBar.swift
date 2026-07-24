import AppKit
import Foundation

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var timer: Timer?
    private var metrics = ["C—", "G—", "H—"]
    private var tooltip = "NexStatus 正在讀取資料…"

    private var snapshotURL: URL {
        let cache = ProcessInfo.processInfo.environment["NEXSTATUS_CACHE"]
            ?? NSString(string: "~/.cache/nexstatus").expandingTildeInPath
        return URL(fileURLWithPath: cache).appendingPathComponent("status.json")
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.isVisible = true
        if let button = statusItem.button {
            button.target = self
            button.action = #selector(openPanel)
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
            button.imagePosition = .noImage
        }

        refreshSnapshot()
        render()
        timer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in
            guard let self else { return }
            self.refreshSnapshot()
            self.render()
            self.keepVisible()
        }
        RunLoop.main.add(timer!, forMode: .common)

        for delay in [0.3, 1.0, 2.0, 4.0] {
            Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
                self?.render()
                self?.keepVisible()
            }
        }
    }

    private func dictionary(_ value: Any?) -> [String: Any] {
        value as? [String: Any] ?? [:]
    }

    private func percent(_ value: Any?) -> Int? {
        if let number = value as? NSNumber { return min(100, max(0, number.intValue)) }
        if let text = value as? String, let number = Double(text) {
            return min(100, max(0, Int(number.rounded())))
        }
        return nil
    }

    private func label(_ prefix: String, _ value: Int?, warning: Bool = false) -> String {
        guard let value else { return "\(prefix)—" }
        return "\(prefix)\(warning && value >= 80 ? "!" : "")\(value)%"
    }

    private func refreshSnapshot() {
        guard let data = try? Data(contentsOf: snapshotURL),
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            metrics = ["C—", "G—", "H—"]
            tooltip = "NexStatus 快照尚未就緒"
            return
        }

        let claude = dictionary(root["claude"])
        let codex = dictionary(root["codex"])
        let host = dictionary(root["host"])
        // Prefer 5h; fall back to 7d when provider only reports weekly (Codex often does).
        let (c, cWindow) = menuQuota(claude)
        let (g, gWindow) = menuQuota(codex)
        var h = percent(host["pressure_pct"])
        if h == nil {
            let cpu = percent(host["cpu_pct"]) ?? 0
            let mem = percent(host["mem_pct"]) ?? 0
            h = Int((0.45 * Double(cpu) + 0.55 * Double(mem)).rounded())
        }
        let mem = percent(host["mem_pct"])
        let swapMb: Double = {
            if let number = host["swap_mb"] as? NSNumber { return number.doubleValue }
            if let text = host["swap_mb"] as? String, let value = Double(text) { return value }
            return 0
        }()
        // Compact human size for tooltip only — never "S13935M" on the MenuBar title.
        let swapLine: String = {
            if swapMb <= 0 { return "Swap：0" }
            if swapMb >= 1024 {
                return String(format: "Swap：%.1f GB", swapMb / 1024.0)
            }
            return String(format: "Swap：%.0f MB", swapMb)
        }()

        // Title stays C / G / H only. Swap is folded into H (collector) and tooltip.
        metrics = [label("C", c), label("G", g), label("H", h, warning: true)]
        tooltip = [
            "NexStatus",
            "Claude \(cWindow)：\(c.map { "\($0)%" } ?? "無資料")",
            "Codex \(gWindow)：\(g.map { "\($0)%" } ?? "無資料")",
            "電腦壓力：\(h.map { "\($0)%" } ?? "無資料")",
            "MEM：\(mem.map { "\($0)%" } ?? "無資料")",
            swapLine,
            "點一下開啟完整面板"
        ].joined(separator: "\n")
    }

    /// Prefer short 5h window; fall back to 7d so menu is not blank when secondary is null.
    private func menuQuota(_ provider: [String: Any]) -> (Int?, String) {
        if let five = percent(provider["five_hour_pct"]) {
            return (five, "5h")
        }
        if let seven = percent(provider["seven_day_pct"]) {
            return (seven, "7d")
        }
        return (nil, "額度")
    }

    private func render() {
        guard let button = statusItem.button else { return }
        let text = metrics.joined(separator: "  ")
        let font = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .semibold)
        button.attributedTitle = NSAttributedString(string: text, attributes: [
            .font: font,
            .foregroundColor: NSColor.labelColor
        ])
        button.toolTip = tooltip
        statusItem.length = ceil((text as NSString).size(withAttributes: [.font: font]).width) + 14
        statusItem.isVisible = true
    }

    /// Tahoe can restore third-party status items underneath the clock. Moving the
    /// status button's private window is the only reliable recovery once that occurs.
    private func keepVisible() {
        guard let window = statusItem.button?.window,
              let screen = NSScreen.screens.first(where: { $0.frame.intersects(window.frame) }) ?? NSScreen.main
        else { return }
        let rightSystemReserve: CGFloat = 320
        let maximumX = screen.frame.maxX - rightSystemReserve
        if window.frame.maxX > maximumX || window.frame.minX < screen.frame.minX {
            var frame = window.frame
            frame.origin.x = maximumX - frame.width
            frame.origin.y = screen.frame.maxY - frame.height
            window.setFrame(frame, display: true)
        }
        statusItem.isVisible = true
    }

    @objc private func openPanel() {
        guard Thread.isMainThread else {
            DispatchQueue.main.async { self.openPanel() }
            return
        }

        DistributedNotificationCenter.default().postNotificationName(
            Notification.Name("com.nexstatus.open-panel"),
            object: nil,
            userInfo: nil,
            deliverImmediately: true
        )
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
