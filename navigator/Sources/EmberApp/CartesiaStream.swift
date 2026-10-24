import Foundation
import AVFoundation
import EmberCore

/// Cartesia streaming TTS over WebSocket (online only). Opened at launch when there is signal; raw float PCM
/// chunks are scheduled on an AVAudioPlayerNode as they arrive. `speak` reports false if no audio arrives within
/// the budget (500 ms), so the Speaker can fall back to Apple TTS without a gap.
final class CartesiaStream: NSObject, @unchecked Sendable {
    static let url = "wss://api.cartesia.ai/tts/websocket"
    static let version = "2026-08-14"     // same Cartesia-Version the staff pre-generation uses
    static let model = "sonic-2"
    static let sampleRate = 44100.0

    private let apiKey: String
    private let lock = NSLock()
    private var task: URLSessionWebSocketTask?
    private var session: URLSession?
    private var activeContext: String?
    private var gotChunk = false
    private var gotDone = false
    private var failed = false
    private var pendingBuffers = 0
    private let engine = AVAudioEngine()
    private let node = AVAudioPlayerNode()
    private let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: CartesiaStream.sampleRate, channels: 1, interleaved: false)!

    init(apiKey: String) {
        self.apiKey = apiKey
        super.init()
        engine.attach(node)
        engine.connect(node, to: engine.mainMixerNode, format: format)
    }

    var isOpen: Bool { lock.sync { task != nil && task?.state == .running } }

    func open() {
        lock.lock(); defer { lock.unlock() }
        guard task == nil || task?.state != .running else { return }
        var c = URLComponents(string: CartesiaStream.url)!
        c.queryItems = [URLQueryItem(name: "api_key", value: apiKey), URLQueryItem(name: "cartesia_version", value: CartesiaStream.version)]
        var req = URLRequest(url: c.url!)
        req.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        req.setValue(CartesiaStream.version, forHTTPHeaderField: "Cartesia-Version")
        let s = URLSession(configuration: .default)
        let t = s.webSocketTask(with: req)
        session = s
        task = t
        t.resume()
        receive(t)
    }

    func close() {
        lock.sync {
            task?.cancel(with: .goingAway, reason: nil)
            task = nil
        }
    }

    private func receive(_ t: URLSessionWebSocketTask) {
        t.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure:
                self.lock.sync {
                    self.failed = true
                    if self.task === t { self.task = nil }
                }
            case .success(let msg):
                if case .string(let s) = msg { self.handle(Data(s.utf8)) }
                if case .data(let d) = msg { self.handle(d) }
                self.receive(t)
            }
        }
    }

    private func handle(_ data: Data) {
        guard let o = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        let ctx = o["context_id"] as? String
        lock.lock()
        guard ctx == nil || ctx == activeContext else { lock.unlock(); return }
        let type = o["type"] as? String
        switch type {
        case "chunk":
            lock.unlock()
            if let b64 = o["data"] as? String, let pcm = Data(base64Encoded: b64), let ctx = ctx ?? lock.sync({ activeContext }) {
                schedule(pcm, ctx: ctx)
            }
        case "done":
            gotDone = true
            lock.unlock()
        case "error":
            failed = true
            lock.unlock()
        default:
            lock.unlock()
        }
    }

    private func schedule(_ pcm: Data, ctx: String) {
        let frames = pcm.count / 4
        guard frames > 0, let buf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames)) else { return }
        buf.frameLength = AVAudioFrameCount(frames)
        pcm.withUnsafeBytes { raw in
            if let dst = buf.floatChannelData?[0] { memcpy(dst, raw.baseAddress!, frames * 4) }
        }
        guard lock.sync({ () -> Bool in
            guard activeContext == ctx else { return false }
            gotChunk = true
            pendingBuffers += 1
            return true
        }) else { return }
        if !engine.isRunning { try? engine.start() }
        node.scheduleBuffer(buf) { [weak self] in
            guard let self else { return }
            self.lock.sync { if self.activeContext == ctx { self.pendingBuffers -= 1 } }
        }
        if !node.isPlaying { node.play() }
    }

    /// Speaks `text` (already pronunciation-mapped). Returns false if nothing played within `budget` seconds.
    func speak(_ text: String, voiceId: String, budget: TimeInterval, isCurrent: @escaping () -> Bool) async -> Bool {
        guard let t = lock.sync({ task }), t.state == .running else { return false }
        let ctx = UUID().uuidString
        lock.sync {
            activeContext = ctx
            gotChunk = false; gotDone = false; failed = false; pendingBuffers = 0
        }
        let body: [String: Any] = [
            "model_id": CartesiaStream.model, "transcript": text, "voice": ["mode": "id", "id": voiceId],
            "output_format": ["container": "raw", "encoding": "pcm_f32le", "sample_rate": Int(CartesiaStream.sampleRate)],
            "context_id": ctx, "continue": false, "language": "en",
        ]
        guard let d = try? JSONSerialization.data(withJSONObject: body), let s = String(data: d, encoding: .utf8) else { return false }
        t.send(.string(s)) { [weak self] err in if err != nil { self?.lock.sync { self?.failed = true } } }

        let start = Date()
        while Date().timeIntervalSince(start) < budget {
            let (chunk, fail) = lock.sync { (gotChunk, failed) }
            if chunk { break }
            if fail { break }
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        guard lock.sync({ gotChunk }) else {
            stop()
            return false
        }
        while isCurrent() {
            let (done, pending, fail) = lock.sync { (gotDone, pendingBuffers, failed) }
            if (done || fail) && pending <= 0 { break }
            try? await Task.sleep(nanoseconds: 50_000_000)
        }
        return true
    }

    func stop() {
        let ctx: String? = lock.sync {
            let c = activeContext
            activeContext = nil
            pendingBuffers = 0
            return c
        }
        node.stop()
        if let ctx, let t = lock.sync({ task }) {
            let cancel = "{\"context_id\":\"\(ctx)\",\"cancel\":true}"
            t.send(.string(cancel)) { _ in }
        }
    }
}

extension NSLock {
    func sync<T>(_ body: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try body()
    }
}
