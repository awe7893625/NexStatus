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
        let c = percent(claude["five_hour_pct"])
        let g = percent(codex["five_hour_pct"])
        var h = percent(host["pressure_pct"])
        if h == nil {
            let cpu = percent(host["cpu_pct"]) ?? 0
            let mem = percent(host["mem_pct"]) ?? 0
            h = Int((0.45 * Double(cpu) + 0.55 * Double(mem)).rounded())
        }
        metrics = [label("C", c), label("G", g), label("H", h, warning: true)]
        tooltip = [
            "NexStatus",
            "Claude 5h：\(c.map { "\($0)%" } ?? "無資料")",
            "Codex 5h：\(g.map { "\($0)%" } ?? "無資料")",
            "電腦壓力：\(h.map { "\($0)%" } ?? "無資料")",
            "點一下開啟完整面板"
        ].joined(separator: "\n")
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
        guard let url = URL(string: "hammerspoon://nexstatus") else { return }
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = false
        NSWorkspace.shared.open(url, configuration: configuration) { _, error in
            if let error {
                NSLog("NexStatus URL callback failed: %@", error.localizedDescription)
            }
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
